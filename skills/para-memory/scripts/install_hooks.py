#!/usr/bin/env python3
"""Install the conversation-capture hook into ~/.claude/hooks/para-memory/.

The registered command has to be runnable *as written*, from an environment you
did not test in:

- `python` does not exist on a stock macOS (only `python3`), so a bare
  `python <script>` hook fails with "command not found" and the capture silently
  never happens.
- PATH at hook time is not your shell's PATH, so the interpreter is pinned to
  the absolute `sys.executable` that ran this installer, and the script path is
  shell-quoted (it lives under a path with spaces for some users).
- The settings file is someone else's configuration: it is written through a
  temp file + rename so a crash cannot truncate it.

Usage: python3 install_hooks.py [--settings PATH] [--hooks-dir PATH]
"""

import argparse
import json
import shlex
import shutil
import sys
from pathlib import Path

from atomic_io import write_text_atomic

SCRIPTS_DIR = Path(__file__).resolve().parent
SCRIPTS_TO_COPY = ("save_chat_history.py", "atomic_io.py")
HOOK_EVENTS = {
    "SessionEnd": "Persist the whole session when it ends",
    "Stop": "Re-capture after each reply (idempotent: the file is re-rendered)",
}
DEFAULT_SETTINGS_FILE = Path.home() / ".claude" / "settings.json"
DEFAULT_HOOKS_DEST = Path.home() / ".claude" / "hooks" / "para-memory"


def copy_scripts(dest=None):
    hooks_dest = Path(dest) if dest else DEFAULT_HOOKS_DEST
    hooks_dest.mkdir(parents=True, exist_ok=True)
    for name in SCRIPTS_TO_COPY:
        src = SCRIPTS_DIR / name
        dst = hooks_dest / name
        shutil.copy2(src, dst)
        print(f"Copied {src} -> {dst}")
    return hooks_dest


def build_hook_command(script_path, interpreter=None):
    """`<absolute interpreter> <absolute script>`, quoted for a POSIX shell."""
    exe = interpreter or sys.executable
    return f"{shlex.quote(str(exe))} {shlex.quote(str(script_path))}"


def interpreter_risk(executable, prefix=None, base_prefix=None):
    """Empty string when the interpreter looks durable, else a warning.

    Pinning `sys.executable` is right — except when it lives in a throwaway
    virtualenv or under /tmp. The hook would survive that and the interpreter
    would not: capture stops silently weeks later, which is the same failure
    mode this installer was fixed to remove, just later.
    """
    path = str(executable)
    reasons = []
    if prefix and base_prefix and prefix != base_prefix:
        reasons.append("在虚拟环境里")
    if path.startswith(("/tmp/", "/private/tmp/", "/var/folders/")):
        reasons.append("在临时目录里")
    if not reasons:
        return ""
    return (
        f"{path} {'、'.join(reasons)}：那个目录删掉后 hook 会静默停摆（捕获从此不再发生）。"
        "要长期使用，请用系统 python3 跑安装器，或显式指定 --python <绝对路径>"
    )


def resolve_interpreter(explicit=None):
    """The interpreter to bake into the hook command."""
    return Path(explicit).expanduser() if explicit else Path(sys.executable)


def _upsert_hook_entry(hook_list, new_entry):
    """Replace an existing save_chat_history entry in hook_list, or append."""
    for i, entry in enumerate(hook_list):
        for hook in entry.get("hooks", []):
            if "save_chat_history.py" in hook.get("command", ""):
                hook_list[i] = new_entry
                return
    hook_list.append(new_entry)


def register_hook(settings_file=None, hooks_dest=None, interpreter=None):
    settings_file = Path(settings_file) if settings_file else DEFAULT_SETTINGS_FILE
    hooks_dest = Path(hooks_dest) if hooks_dest else DEFAULT_HOOKS_DEST
    interpreter = resolve_interpreter(interpreter)

    script = hooks_dest / "save_chat_history.py"
    if not script.is_file():
        raise SystemExit(
            f"{script} 不存在：先 copy_scripts() 把脚本拷过去，否则注册出来的命令必然失败"
        )

    settings = {}
    if settings_file.exists():
        raw = settings_file.read_text(encoding="utf-8").strip()
        if raw:
            settings = json.loads(raw)

    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit(f'{settings_file}: "hooks" 不是对象，先手工修好再装')

    command = build_hook_command(script, interpreter)
    for event, description in HOOK_EVENTS.items():
        entry = {
            "matcher": "*",
            "hooks": [{"type": "command", "command": command}],
            "description": description,
        }
        _upsert_hook_entry(hooks.setdefault(event, []), entry)

    write_text_atomic(settings_file, json.dumps(settings, indent=2) + "\n")
    print(f"Updated {settings_file}: {', '.join(HOOK_EVENTS)} -> {command}")
    print(f"Interpreter: {interpreter}")
    return command


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--settings", dest="settings_file", default=None,
                        help=f"settings.json to edit (default: {DEFAULT_SETTINGS_FILE})")
    parser.add_argument("--hooks-dir", dest="hooks_dest", default=None,
                        help=f"where to copy the scripts (default: {DEFAULT_HOOKS_DEST})")
    parser.add_argument("--python", dest="python", default=None,
                        help="interpreter to bake into the hook command "
                             "(default: the one running this installer)")
    args = parser.parse_args(argv)

    interpreter = resolve_interpreter(args.python)
    warning = interpreter_risk(interpreter, sys.prefix, sys.base_prefix)
    if warning:
        print(f"⚠ {warning}")

    try:
        hooks_dest = copy_scripts(args.hooks_dest)
        register_hook(
            settings_file=args.settings_file,
            hooks_dest=hooks_dest,
            interpreter=interpreter,
        )
    except OSError as exc:
        print(f"✗ 安装失败：{exc}", file=sys.stderr)
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
