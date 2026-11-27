#!/usr/bin/env python3
"""
SessionEnd hook: save the raw conversation to a per-session markdown file.

Inspired by:
  https://github.com/affaan-m/everything-claude-code/blob/main/scripts/hooks/session-end.js

Hook input (stdin): JSON with {"transcript_path": "..."}
Output: ${PARA_MEMORY_ROOT:-~/para-memory}/memory/YYYY-MM-DD-<shortId>-session.md

Two rules this file has to keep, because it runs unattended inside a host hook:

1. **One session, one file, always fully re-rendered.** The transcript grows; the
   file is rebuilt from it every time, never patched. Patching only the timestamp
   is how a session silently keeps the first turn and loses the rest.
2. **No environment assumptions.** It must run on the oldest Python the host may
   have, and it must not depend on a `python` shim existing on PATH.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from atomic_io import copy_file_atomic, write_text_atomic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_sessions_dir() -> Path:
    root = os.environ.get("PARA_MEMORY_ROOT", "~/para-memory")
    return Path(root).expanduser() / "memory"


def get_short_id(session_id: str) -> str:
    """A filename-safe prefix of the session id (also keeps globs literal)."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", (session_id or "")[:8]).strip("-")
    return safe or "unknown"


def session_short_id(session_id: str, transcript_path: Path) -> str:
    """Filename prefix: the session id when there is one, else the transcript's hash.

    Two captures that carry no session id must not land in the same file — that
    would be the same "two sessions, one file" bug in a different disguise.
    """
    if session_id:
        return get_short_id(session_id)
    digest = hashlib.sha1(str(transcript_path).encode("utf-8")).hexdigest()
    return f"noid-{digest[:6]}"


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def extract_text(content) -> str:
    """Return plain text from a message content field (str or list of blocks)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            b.get("text", "").strip()
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n\n".join(p for p in parts if p)
    return ""


def parse_transcript(
    transcript_path: str, fallback_meta: dict | None = None
) -> tuple[list[dict], dict]:
    """
    Parse a JSONL transcript from either Claude Code or Cursor.

    Claude Code entries use {"type": "user"|"assistant", "sessionId": ..., "cwd": ...}.
    Cursor entries use {"role": "user"|"assistant"} with no session metadata inline.

    Returns:
        messages: [{"role": "user"|"assistant", "text": str}, ...]
        meta:     {"session_id": str, "slug": str, "cwd": str,
                   "tools_used": list[str], "files_modified": list[str]}
    """
    messages: list[dict] = []
    meta = {"session_id": "", "slug": "", "cwd": "", "tools_used": [], "files_modified": []}
    tools_used: set[str] = set()
    files_modified: set[str] = set()
    parse_errors = 0

    for line in Path(transcript_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue

        # Claude Code inline metadata
        if not meta["session_id"] and entry.get("sessionId"):
            meta["session_id"] = entry["sessionId"]
        if not meta["slug"] and entry.get("slug"):
            meta["slug"] = entry["slug"]
        if not meta["cwd"] and entry.get("cwd"):
            meta["cwd"] = entry["cwd"]

        # Support both Claude Code ("type") and Cursor ("role") formats
        entry_type = entry.get("type") or entry.get("role", "")

        # User messages (skip isMeta entries)
        if entry_type == "user" and not entry.get("isMeta"):
            raw = entry.get("message", {}).get("content") or entry.get("content", "")
            text = extract_text(raw)
            if text:
                messages.append({"role": "user", "text": text})

        # Assistant messages — merge consecutive streaming updates;
        # also collect tool_use blocks
        elif entry_type == "assistant":
            content = entry.get("message", {}).get("content", [])
            text = extract_text(content)
            if text:
                if messages and messages[-1]["role"] == "assistant":
                    messages[-1]["text"] = text  # replace with latest (most complete)
                else:
                    messages.append({"role": "assistant", "text": text})
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    tool_name = block.get("name") or ""
                    if tool_name:
                        tools_used.add(tool_name)
                    file_path = block.get("input", {}).get("file_path") or ""
                    if file_path and tool_name in ("Edit", "Write"):
                        files_modified.add(file_path)

        # Direct tool_use entries (Claude Code only)
        elif entry_type == "tool_use" or entry.get("tool_name"):
            tool_name = entry.get("tool_name") or entry.get("name") or ""
            if tool_name:
                tools_used.add(tool_name)
            file_path = (
                entry.get("tool_input", {}).get("file_path")
                or entry.get("input", {}).get("file_path")
                or ""
            )
            if file_path and tool_name in ("Edit", "Write"):
                files_modified.add(file_path)

    if parse_errors:
        print(f"[SessionEnd] Skipped {parse_errors} unparseable lines", file=sys.stderr)

    # Fill missing metadata from hook input (Cursor doesn't embed these in transcript)
    if fallback_meta:
        for key in ("session_id", "slug", "cwd"):
            if not meta[key] and fallback_meta.get(key):
                meta[key] = fallback_meta[key]

    meta["tools_used"] = sorted(tools_used)
    meta["files_modified"] = sorted(files_modified)
    return messages, meta


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def build_conversation(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        label = "**User**" if msg["role"] == "user" else "**Assistant**"
        lines.append(f"{label}: {msg['text']}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session file management
# ---------------------------------------------------------------------------

def read_header_value(content: str, key: str) -> str:
    """Read one `**Key:** value` line out of an already captured session file."""
    match = re.search(rf"^\*\*{re.escape(key)}:\*\* ?(.*)$", content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def read_head(path: Path, max_lines: int = 12) -> str:
    """The top of a captured file, where its identity is written.

    Line-based, not byte-based: a very long slug must not push the
    `**Session:**` line out of the window and turn a known session into a new file.
    """
    lines = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for _ in range(max_lines):
            line = handle.readline(65536)
            if not line:
                break
            lines.append(line)
    return "".join(lines)


def file_owner(path: Path) -> str:
    """The session id written in this file's header, or "" when it has none."""
    try:
        return read_header_value(read_head(path), "Session")
    except OSError:
        return ""


def _disambiguated(default: Path, key: str) -> Path:
    """`…-<short>-session.md` -> `…-<short>-<4 hex>-session.md`, stable per key."""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:4]
    base = default.name[: -len("-session.md")]
    return default.with_name(f"{base}-{digest}-session.md")


def find_session_file(
    sessions_dir: Path,
    session_id: str,
    short_id: str,
    today: str,
    no_id_key: str = "",
) -> Path:
    """The file this capture may write, or the name a brand-new one gets.

    Ownership is decided by the `**Session:**` line *inside* the file, never by the
    filename. `get_short_id` truncates to eight characters and normalises the rest
    to `-`, so `ab-12345…` and `ab.12345…` shorten to the same `ab-12345`; matching
    on the name lets the second session re-render away the first one's whole file.

    Three rules follow from that:

    * a session with an id only ever writes into a file whose header names *that*
      id (or into a fresh file when the plain name is free);
    * a capture without an id (a `.txt` transcript) only adopts a file **nobody
      claims** — a file with a `**Session:**` header can be re-captured from its own
      transcript, so overwriting it would delete a conversation with no trace;
    * when the plain name is already taken by somebody else, a stable four-hex
      suffix derived from the capture's own key is added, so the same capture keeps
      landing in the same file and two captures never share one.

    A session can still be running when the clock rolls past midnight: the first
    capture names the file after the day it started, and later captures find it by
    header, so one conversation does not get split across two files.
    """
    default = sessions_dir / f"{today}-{short_id}-session.md"
    if not sessions_dir.exists() or short_id == "unknown":
        return default

    # Both shapes: `…-<short>-session.md` and the disambiguated `…-<short>-<digest>-session.md`.
    candidates = sorted(sessions_dir.glob(f"*-{short_id}-session.md")) + sorted(
        sessions_dir.glob(f"*-{short_id}-*-session.md")
    )
    if not candidates:
        return default

    if session_id:
        for path in candidates:
            if file_owner(path) == session_id:
                return path
        if file_owner(default) not in ("", session_id):
            return _disambiguated(default, session_id)
        return default

    # No session id: the name prefix is all there is, and only unclaimed files are fair game.
    for path in candidates:
        if not file_owner(path):
            return path
    if file_owner(default):
        return _disambiguated(default, no_id_key or short_id)
    return default


def render_session_file(
    *,
    slug: str,
    session_id: str,
    day: str,
    project: str,
    started: str,
    updated: str,
    tools_used: list[str],
    files_modified: list[str],
    messages: list[dict],
) -> str:
    """Render the whole file from the transcript; only the stamps are carried over."""
    tools_line = ", ".join(tools_used) if tools_used else "—"
    files_lines = (
        "\n".join(f"- {f}" for f in files_modified) if files_modified else "—"
    )
    identity = f"**Session:** {session_id}\n" if session_id else ""
    return (
        f"# Session: {slug}\n"
        f"{identity}"
        f"**Date:** {day}\n"
        f"**Project:** {project}\n"
        f"**Started:** {started}\n"
        f"**Last Updated:** {updated}\n\n"
        f"**Tools:** {tools_line}\n\n"
        f"**Files Modified:**\n{files_lines}\n\n"
        f"---\n\n"
        f"{build_conversation(messages)}"
    )


def run(transcript_path: str, fallback_meta: dict | None = None) -> None:
    p = Path(transcript_path)

    sessions_dir = get_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()

    # .txt files: copy content directly (same naming rule as the JSONL path, so a
    # transcript captured across midnight stays in the file it started in)
    if p.suffix.lower() == ".txt":
        session_file = find_session_file(
            sessions_dir,
            "",
            get_short_id(p.stem),
            now.strftime("%Y-%m-%d"),
            no_id_key=str(p.resolve()),
        )
        copy_file_atomic(p, session_file)
        print(f"[SessionEnd] Copied txt to session file: {session_file}", file=sys.stderr)
        return

    # Default: parse as JSONL (supports both Claude Code and Cursor formats)
    messages, meta = parse_transcript(transcript_path, fallback_meta)

    # Skip trivial sessions (fewer than 2 meaningful exchanges)
    if sum(1 for m in messages if len(m["text"]) > 20) < 2:
        return

    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    short_id = session_short_id(meta["session_id"], p)
    session_file = find_session_file(sessions_dir, meta["session_id"], short_id, today)
    project = os.path.basename(meta["cwd"]) if meta["cwd"] else "unknown"
    slug = meta["slug"] or short_id

    existed = session_file.exists()
    day, started = today, current_time
    if existed:
        previous = session_file.read_text(encoding="utf-8")
        day = read_header_value(previous, "Date") or today
        started = read_header_value(previous, "Started") or current_time

    write_text_atomic(
        session_file,
        render_session_file(
            slug=slug,
            session_id=meta["session_id"],
            day=day,
            project=project,
            started=started,
            updated=current_time,
            tools_used=meta["tools_used"],
            files_modified=meta["files_modified"],
            messages=messages,
        ),
    )
    verb = "Updated" if existed else "Created"
    print(
        f"[SessionEnd] {verb} session file: {session_file} ({len(messages)} messages)",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        sys.exit(0)

    if hook_input.get("stop_hook_active"):
        sys.exit(0)

    transcript_path = hook_input.get("transcript_path") or os.environ.get(
        "CLAUDE_TRANSCRIPT_PATH"
    )
    if not transcript_path or not Path(transcript_path).exists():
        sys.exit(0)

    # Build fallback metadata for Cursor format (session info is in hook input, not transcript)
    workspace_roots = hook_input.get("workspace_roots") or []
    fallback_meta = {
        "session_id": hook_input.get("session_id") or hook_input.get("conversation_id", ""),
        "cwd": workspace_roots[0] if workspace_roots else "",
    }

    run(transcript_path, fallback_meta)


if __name__ == "__main__":
    main()
