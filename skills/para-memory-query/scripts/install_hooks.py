#!/usr/bin/env python3
"""Install para-memory-query PreToolUse hook into ~/.claude/hooks/para-memory/ and register in settings.json."""

import json
import shutil
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
HOOKS_DEST = Path.home() / ".claude" / "hooks" / "para-memory"
SCRIPTS_DEST = HOOKS_DEST / "scripts"
SETTINGS_FILE = Path.home() / ".claude" / "settings.json"

SCRIPTS_TO_COPY = ["para-memory-query-hook.py"]
SHELL_SCRIPTS_TO_COPY = ["search_timeline.sh", "search_qmd.sh", "query_entity.sh"]


def copy_scripts():
    HOOKS_DEST.mkdir(parents=True, exist_ok=True)
    SCRIPTS_DEST.mkdir(parents=True, exist_ok=True)

    for name in SCRIPTS_TO_COPY:
        src = SCRIPTS_DIR / name
        dst = HOOKS_DEST / name
        shutil.copy2(src, dst)
        print(f"Copied {src} -> {dst}")

    for name in SHELL_SCRIPTS_TO_COPY:
        src = SCRIPTS_DIR / name
        dst = SCRIPTS_DEST / name
        shutil.copy2(src, dst)
        print(f"Copied {src} -> {dst}")


def _upsert_hook_entry(hook_list: list, new_entry: dict) -> None:
    """Replace existing para-memory-query entry in hook_list, or append."""
    for i, entry in enumerate(hook_list):
        for h in entry.get("hooks", []):
            if "para-memory-query-hook.py" in h.get("command", ""):
                hook_list[i] = new_entry
                return
    hook_list.append(new_entry)


def register_hook():
    settings = {}
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            settings = json.load(f)

    hook_command = f"python {HOOKS_DEST / 'para-memory-query-hook.py'}"
    hooks = settings.setdefault("hooks", {})

    pre_tool_use_entry = {
        "matcher": "Grep|Glob|Bash",
        "hooks": [{"type": "command", "command": hook_command}],
        "description": "Inject memory context before code searches",
    }
    _upsert_hook_entry(hooks.setdefault("PreToolUse", []), pre_tool_use_entry)

    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"Updated {SETTINGS_FILE}: PreToolUse hook -> {hook_command}")


if __name__ == "__main__":
    copy_scripts()
    register_hook()
    print("Done.")
