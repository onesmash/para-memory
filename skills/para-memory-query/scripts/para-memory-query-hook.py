#!/usr/bin/env python3
"""PreToolUse hook: intercepts Grep/Glob/Bash calls and injects para-memory context."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def extract_pattern(tool_name: str, tool_input: dict) -> str | None:
    if tool_name == "Grep":
        return tool_input.get("pattern") or None

    if tool_name == "Glob":
        raw = tool_input.get("pattern", "")
        match = re.search(r"[*/]([a-zA-Z][a-zA-Z0-9_-]{2,})", raw)
        return match.group(1) if match else None

    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if not re.search(r"\brg\b|\bgrep\b", cmd):
            return None
        tokens = cmd.split()
        found_cmd = False
        skip_next = False
        flags_with_values = {"-e", "-f", "-m", "-A", "-B", "-C", "-g", "--glob", "-t", "--type", "--include", "--exclude"}
        for token in tokens:
            if skip_next:
                skip_next = False
                continue
            if not found_cmd:
                if re.search(r"\brg$|\bgrep$", token):
                    found_cmd = True
                continue
            if token.startswith("-"):
                if token in flags_with_values:
                    skip_next = True
                continue
            cleaned = token.strip("'\"")
            return cleaned if len(cleaned) >= 3 else None
        return None

    return None


def find_scripts_dir() -> Path | None:
    installed = Path.home() / ".claude" / "hooks" / "para-memory" / "scripts"
    if installed.is_dir():
        return installed
    return None


def run_script(scripts_dir: Path, script: str, *args) -> str:
    result = subprocess.run(
        ["bash", str(scripts_dir / script), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def search_knowledge_graph(scripts_dir: Path, pattern: str) -> str:
    memory_root = os.environ.get("PARA_MEMORY_ROOT", str(Path.home() / "para-memory"))
    knowledge_dir = Path(memory_root) / "knowledge"
    if not knowledge_dir.is_dir():
        return ""

    # Single grep pass to find candidate entity files
    grep = subprocess.run(
        ["grep", "-r", "-i", "-l", pattern, str(knowledge_dir), "--include=items.json"],
        capture_output=True, text=True, check=False,
    )
    candidate_files = [Path(l.strip()) for l in grep.stdout.strip().splitlines() if l.strip()]
    if not candidate_files:
        return ""

    # jq filter: active facts whose text contains the keyword (case-insensitive)
    jq_filter = f'.items[] | select(.status == "active") | select(.fact | test("{pattern}"; "i"))'

    outputs = []
    for items_file in candidate_files:
        entity_path = str(items_file.parent.relative_to(knowledge_dir))
        out = run_script(scripts_dir, "query_entity.sh", entity_path, jq_filter)
        if out:
            outputs.append(f"**{entity_path}**\n{out}")

    return "\n\n".join(outputs)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    if data.get("hook_event_name") != "PreToolUse":
        return

    tool_name = data.get("tool_name", "")
    if tool_name not in {"Grep", "Glob", "Bash"}:
        return

    pattern = extract_pattern(tool_name, data.get("tool_input", {}))
    if not pattern or len(pattern) < 3:
        return

    scripts_dir = find_scripts_dir()
    if scripts_dir is None:
        return

    timeline_out = run_script(scripts_dir, "search_timeline.sh", "keyword", pattern)
    entity_out = search_knowledge_graph(scripts_dir, pattern)
    semantic_out = run_script(scripts_dir, "search_qmd.sh", pattern)

    parts = []
    if timeline_out:
        parts.append(f"### Timeline\n{timeline_out}")
    if entity_out:
        parts.append(f"### Knowledge Graph\n{entity_out}")
    if semantic_out:
        parts.append(f"### Semantic\n{semantic_out}")

    if not parts:
        return

    context = "## Memory Context\n\n" + "\n\n".join(parts)
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": context,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"para-memory-query hook error: {e}", file=sys.stderr)
