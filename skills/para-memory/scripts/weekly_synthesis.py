#!/usr/bin/env python3
"""
Apply memory decay and regenerate entity summaries.

Sorts facts into tiers:
- Hot (accessed last 7 days)
- Warm (accessed 8-30 days ago)
- Cold (not accessed 30+ days) - omitted from summary

After regenerating summaries, refreshes the QMD index for the memory
collections. If that refresh fails, the run exits non-zero: a summary that says
"done" while the index still serves yesterday's content is worse than a loud
failure.

Usage: python3 weekly_synthesis.py [base_path] [--skip-qmd]
If base_path is not provided, uses PARA_MEMORY_ROOT environment variable.
If environment variable not set, defaults to ~/para-memory/knowledge.

Environment:
  QMD_BIN                    qmd executable (default: PATH, then common bin dirs)
  QMD_COLLECTIONS            collections to embed (default: "knowledge daily")
  QMD_EMBED_TIMEOUT_MINUTES  cap handed to `qmd embed`; 0 = no limit (default)

Why there is no wall-clock kill around qmd: a kill in the middle of an embed
leaves partial vectors on disk and cannot be told apart from a clean run. qmd
owns that decision through `--timeout`, and its own default (30 min) truncates
the run while still printing "✓ Done!" with exit code 0 — measured with
`--timeout 0.05`, which stopped at 13s and reported success. So the default
here is explicitly 0 (no limit) and the exit code is what we trust.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from atomic_io import write_text_atomic

QMD_INSTALL_HINT = "npm install -g @tobilu/qmd"
DEFAULT_COLLECTIONS = ("knowledge", "daily")
QMD_FALLBACK_PATHS = (
    "/usr/local/bin/qmd",
    "/opt/homebrew/bin/qmd",
    "~/local/bin/qmd",
    "~/.local/bin/qmd",
)


def days_since_access(last_accessed):
    """Calculate days since last access."""
    if not last_accessed:
        return 999  # Very old

    try:
        last_date = datetime.strptime(last_accessed, "%Y-%m-%d")
        return (datetime.now() - last_date).days
    except (ValueError, TypeError):
        return 999


def classify_fact(fact):
    """Classify fact as hot, warm, or cold."""
    days = days_since_access(fact.get("lastAccessed"))
    access_count = fact.get("accessCount", 0)

    # Frequency resistance: high access count extends warmth
    if access_count > 10:
        days = max(0, days - 5)  # Bonus 5 days

    if days <= 7:
        return "hot"
    elif days <= 30:
        return "warm"
    else:
        return "cold"


def get_base_path(provided_path=None):
    """Get base path from argument, environment variable, or default."""
    if provided_path:
        return Path(os.path.expanduser(provided_path))

    env_path = os.environ.get('PARA_MEMORY_ROOT')
    if env_path:
        return Path(os.path.expanduser(env_path))

    # Default path
    return Path(os.path.expanduser('~/para-memory/knowledge'))


def extract_overview(content):
    """The hand-written `# Title` + `## Overview` part of an existing summary.

    Returns "" when the file does not have that shape. The previous code split the
    file on "## Hot Facts" and kept *everything* before it, so any summary written
    by an older version (or by hand) came back in full on every run and its stale
    lines became permanent.
    """
    title = ""
    lines = content.lstrip().splitlines()
    if lines and lines[0].startswith("# "):
        title = lines[0].strip()

    match = re.search(
        r"^## Overview[ \t]*$\n(.*?)(?=^## |\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not match or not match.group(1).strip():
        return ""

    header = f"{title}\n\n" if title else ""
    return f"{header}## Overview\n\n{match.group(1).strip()}"


def regenerate_summary(entity_path):
    """Regenerate summary.md from items.json with memory decay."""
    items_path = entity_path / "items.json"
    summary_path = entity_path / "summary.md"

    if not items_path.exists():
        return 0, 0, 0

    data = json.loads(items_path.read_text())
    active_facts = [f for f in data["items"] if f.get("status") == "active"]

    # Classify facts
    hot_facts = []
    warm_facts = []
    cold_facts = []

    for fact in active_facts:
        tier = classify_fact(fact)
        if tier == "hot":
            hot_facts.append(fact)
        elif tier == "warm":
            warm_facts.append(fact)
        else:
            cold_facts.append(fact)

    # Sort by access count within tiers
    hot_facts.sort(key=lambda f: f.get("accessCount", 0), reverse=True)
    warm_facts.sort(key=lambda f: f.get("accessCount", 0), reverse=True)

    # Keep only the hand-written overview; everything below it is generated.
    overview = ""
    if summary_path.exists():
        overview = extract_overview(summary_path.read_text(encoding="utf-8"))

    # Generate new summary
    entity_name = entity_path.name.replace("-", " ").title()
    summary_content = overview if overview else f"# {entity_name}\n\n## Overview\n\n"

    summary_content += "\n## Hot Facts\n\n"
    if hot_facts:
        for fact in hot_facts:
            summary_content += f"- {fact['fact']} ({fact.get('timestamp', 'unknown')})\n"
    else:
        summary_content += "*No recently accessed facts*\n"

    summary_content += "\n## Warm Facts\n\n"
    if warm_facts:
        for fact in warm_facts:
            summary_content += f"- {fact['fact']} ({fact.get('timestamp', 'unknown')})\n"
    else:
        summary_content += "*No warm facts*\n"

    # Note cold facts exist but don't list them
    if cold_facts:
        summary_content += f"\n## Archived Facts\n\n*{len(cold_facts)} cold facts available in items.json*\n"

    # Related entities
    all_related = set()
    for fact in active_facts:
        all_related.update(fact.get("relatedEntities", []))

    if all_related:
        summary_content += "\n## Related Entities\n\n"
        for entity in sorted(all_related):
            summary_content += f"- {entity}\n"

    # Atomic: a crash must leave the previous summary, not half of the new one.
    write_text_atomic(summary_path, summary_content)
    return len(hot_facts), len(warm_facts), len(cold_facts)


# ---------------------------------------------------------------------------
# QMD index maintenance
# ---------------------------------------------------------------------------

def resolve_qmd():
    """Absolute path to the qmd binary, or None.

    PATH is not enough: an agent host often runs without the npm global bin
    directory on PATH (that is how the very first weekly synthesis "skipped"
    the index on this machine while qmd was installed all along).
    """
    explicit = os.environ.get("QMD_BIN", "").strip()
    if explicit:
        return explicit if Path(explicit).is_file() and os.access(explicit, os.X_OK) else None

    found = shutil.which("qmd")
    if found:
        return found

    for candidate in QMD_FALLBACK_PATHS:
        path = Path(os.path.expanduser(candidate))
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def memory_collections():
    """Collections that belong to memory; never the user's other indexes."""
    raw = os.environ.get("QMD_COLLECTIONS", "")
    named = [part for part in re.split(r"[,\s]+", raw.strip()) if part]
    return named or list(DEFAULT_COLLECTIONS)


def embed_timeout_minutes():
    """Value for qmd's own `--timeout`; 0 = no limit. qmd validates it."""
    return os.environ.get("QMD_EMBED_TIMEOUT_MINUTES", "").strip() or "0"


def _run_qmd(binary, args):
    """Run one qmd command. Returns (ok, detail).

    qmd is a Node CLI whose launcher starts with `#!/usr/bin/env node`, so
    resolving the qmd path is not enough: `node` has to be findable too. It
    usually sits in the same bin directory, and a hook environment often has
    neither on PATH — measured on this machine, an absolute qmd path still died
    with `env: node: No such file or directory`. So the child gets its own bin
    directory prepended to PATH.
    """
    env = dict(os.environ)
    env["PATH"] = str(Path(binary).parent) + os.pathsep + env.get("PATH", "")
    try:
        result = subprocess.run(
            [binary, *args], capture_output=True, text=True, env=env
        )
    except OSError as exc:
        return False, f"{binary}: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"rc={result.returncode}"
        return False, detail
    return True, (result.stdout or "").strip()


def update_qmd_index():
    """Refresh the qmd index and the memory embeddings. Returns (ok, reason)."""
    print("\nUpdating QMD search index...")

    binary = resolve_qmd()
    if not binary:
        explicit = os.environ.get("QMD_BIN", "").strip()
        where = f"QMD_BIN={explicit} 不可执行" if explicit else "PATH 与常见 bin 目录里都没有 qmd"
        reason = f"找不到 qmd（{where}）。安装：{QMD_INSTALL_HINT}"
        print(f"  ✗ {reason}")
        return False, reason

    # `qmd update` has no per-collection filter — `qmd update -c x` silently
    # ignores the flag and refreshes every collection (measured 2026-11-27).
    # That is a file-listing hash pass, not an embedding run, so leaving it
    # global is cheap; the expensive half below is scoped per collection.
    ok, detail = _run_qmd(binary, ["update"])
    if not ok:
        reason = f"qmd update 失败：{detail}"
        print(f"  ✗ {reason}")
        return False, reason
    print("  ✓ qmd update ok（该命令没有集合过滤，刷新的是全部集合的文件索引）")

    failures = []
    timeout = embed_timeout_minutes()
    for collection in memory_collections():
        # `qmd embed` 只认第一个 -c，所以一次一个集合。
        ok, detail = _run_qmd(
            binary, ["embed", "-c", collection, "--timeout", timeout]
        )
        if ok:
            print(f"  ✓ embed {collection} ok")
        else:
            failures.append(f"{collection}: {detail}")
            print(f"  ✗ embed {collection} 失败：{detail}")

    if failures:
        return False, "; ".join(failures)
    return True, ""


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    skip_qmd = "--skip-qmd" in args
    args = [arg for arg in args if arg != "--skip-qmd"]

    # Handle 0 or 1 positional arguments
    if len(args) > 1:
        print("Usage: python3 weekly_synthesis.py [base_path] [--skip-qmd]")
        print("If base_path is not provided, uses PARA_MEMORY_ROOT environment variable.")
        print("If environment variable not set, defaults to ~/para-memory/knowledge.")
        return 1

    base_path = get_base_path(args[0] if args else None)

    if not base_path.exists():
        print(f"Error: Path not found: {base_path}")
        return 1

    print("Running weekly synthesis...")

    # Find all entity directories (those with items.json)
    entity_paths = [items_file.parent for items_file in base_path.rglob("items.json")]

    total_hot = total_warm = total_cold = 0
    failures = []

    for entity_path in entity_paths:
        try:
            hot, warm, cold = regenerate_summary(entity_path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # One hand-edited or half-written items.json used to abort the whole
            # run: every entity after it got no summary at all, and the failure
            # surfaced as a bare traceback instead of a named one.
            failures.append(f"{entity_path.name}: {exc}")
            print(f"  ✗ {entity_path.name}: 跳过（{exc}）")
            continue
        total_hot += hot
        total_warm += warm
        total_cold += cold
        print(f"  ✓ {entity_path.name}: {hot} hot, {warm} warm, {cold} cold")

    print(f"\n  Total: {total_hot} hot, {total_warm} warm, {total_cold} cold facts")
    print(f"  Processed {len(entity_paths)} entities")

    index_ok = True
    if skip_qmd:
        print("\n⚠ Skipped QMD update (--skip-qmd flag)：索引未更新")
        print("[weekly_synthesis] index=skipped", file=sys.stderr)
    else:
        index_ok, reason = update_qmd_index()
        if index_ok:
            print("\n✓ Synthesis complete")
            print("[weekly_synthesis] index=updated", file=sys.stderr)
        else:
            print("\n✗ Summary files regenerated, but 索引未更新：")
            print(f"  {reason}")
            print("  搜索到的仍是旧索引。修好 qmd 后重跑，或加 --skip-qmd 明确跳过。")
            print("[weekly_synthesis] index=failed", file=sys.stderr)

    if failures:
        # 退出码非 0（有实体没写成功），同时把名单点名，别只留一行 traceback。
        print(f"\n✗ {len(failures)} 个实体没有写出 summary：")
        for line in failures:
            print(f"  - {line}")
        return 1
    return 0 if index_ok else 1


if __name__ == "__main__":
    sys.exit(main())
