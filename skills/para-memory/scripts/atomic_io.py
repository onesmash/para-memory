#!/usr/bin/env python3
"""Atomic text writes shared by the para-memory scripts.

Why this module exists: every file these scripts rewrite is somebody's memory
(an `items.json`, a `summary.md`, a captured session, the host's
`settings.json`). A `write_text()` that dies halfway leaves a truncated file
where the previous version used to be, and nothing later can tell the two
apart. Writing to a sibling temp file and renaming it over the target makes the
swap a single filesystem operation: readers see the old file or the new one,
never half of each.

Two properties this module deliberately keeps:

* **Mode is preserved.** `mkstemp` creates 0600, so a plain rename would silently
  narrow the permissions of `settings.json` or of a shared summary. The mode of an
  existing target is copied onto the temp file before the rename; a new file gets
  the usual `0666 & ~umask`.
* **The temp file is written through the descriptor `mkstemp` returned**, not
  reopened by name, so there is no window in which the path can be swapped.

`os.replace` is atomic only within one filesystem, so the temp file is created in
the target's own directory.

Durability, stated rather than implied: the file contents are fsynced, the
directory entry created by `os.replace` is not. After a power cut the rename may
not be durable, and the file can fall back to its previous version — which is
exactly the contract of this module. The data here is derived (a session file is
re-rendered from the transcript, a summary from `items.json`), so paying for a
parent-directory fsync on every write is not worth it.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

__all__ = ["copy_file_atomic", "write_text_atomic"]


def _target_mode(target: Path) -> int:
    """The mode a rewritten file keeps, or the umask-derived one for a new file."""
    try:
        return stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def _commit(tmp: str, target: Path) -> None:
    os.chmod(tmp, _target_mode(target))
    os.replace(tmp, target)


def _discard(tmp: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(tmp)


def write_text_atomic(path, text: str, encoding: str = "utf-8") -> None:
    """Write `text` to `path` so that a crash leaves the previous version intact."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        # fdopen owns the descriptor from here on; never reopen `tmp` by name.
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _commit(tmp, target)
    except BaseException:
        # Either we never renamed (the temp file is still ours) or the rename
        # itself failed. A stray `.name.XXXX.tmp` would make the next reader
        # guess whether it is data or rubbish.
        _discard(tmp)
        raise


def copy_file_atomic(src, dst) -> None:
    """Copy `src` over `dst` the same way: old file or new file, never half."""
    target = Path(dst)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as writer:
            with open(src, "rb") as reader:
                shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        _commit(tmp, target)
    except BaseException:
        _discard(tmp)
        raise
