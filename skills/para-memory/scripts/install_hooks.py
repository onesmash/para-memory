#!/usr/bin/env python3
"""Install para-memory hooks into ~/.claude/hooks/para-memory/ and register them in settings.json."""

import json
import shutil
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
HOOKS_DEST = Path.home() / ".claude" / "hooks" / "para-memory"
SETTINGS_FILE = Path.home() / ".claude" / "settings.json"
SCRIPTS_TO_COPY = ["save_chat_history.py"]


def copy_scripts():
    HOOKS_DEST.mkdir(parents=True, exist_ok=True)
    for name in SCRIPTS_TO_COPY:
        src = SCRIPTS_DIR / name
        dst = HOOKS_DEST / name
        shutil.copy2(src, dst)
        print(f"Copied {src} -> {dst}")


def register_hook():
    settings = {}
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            settings = json.load(f)

    hook_command = f"python {HOOKS_DEST / 'save_chat_history.py'}"
    new_hook_entry = {
        "matcher": "*",
        "hooks": [{"type": "command", "command": hook_command}],
        "description": "Persist session state on end",
    }

    hooks = settings.setdefault("hooks", {})
    session_end = hooks.setdefault("SessionEnd", [])

    # Replace existing para-memory entry or append
    updated = False
    for i, entry in enumerate(session_end):
        for h in entry.get("hooks", []):
            if "save_chat_history.py" in h.get("command", ""):
                session_end[i] = new_hook_entry
                updated = True
                break
        if updated:
            break
    if not updated:
        session_end.append(new_hook_entry)

    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"Updated {SETTINGS_FILE}: SessionEnd hook -> {hook_command}")


if __name__ == "__main__":
    copy_scripts()
    register_hook()
    print("Done.")
