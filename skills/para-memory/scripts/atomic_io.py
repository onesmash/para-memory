#!/usr/bin/env python3
"""Atomic text writes shared by the para-memory scripts.

Why this module exists: every file these scripts rewrite is somebody's memory
(an `items.json`, a `summary.md`, a captured session, the host's
`settings.json`). A `write_text()` that dies halfway leaves a truncated file
where the previous version used to be, and nothing later can tell the two
apart. Writing to a sibling temp file and renaming it over the target makes the
swap a single filesystem operation: readers see the old file or the new one,
never half of each.

`os.replace` is atomic only within one filesystem, so the temp file is created
in the target's own directory.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from pathlib import Path

__all__ = ["copy_file_atomic", "write_text_atomic"]


@contextlib.contextmanager
def _staged_path(target: Path):
    """Yield a sibling temp path; rename it over `target` only if the block succeeds."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    os.close(fd)
    try:
        yield tmp
        os.replace(tmp, target)
    except BaseException:
        # Either we never renamed (the temp file is still ours) or the rename
        # itself failed. A stray `.name.XXXX.tmp` would make the next reader
        # guess whether it is data or rubbish.
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def write_text_atomic(path, text: str, encoding: str = "utf-8") -> None:
    """Write `text` to `path` so that a crash leaves the previous version intact."""
    target = Path(path)
    with _staged_path(target) as tmp:
        with open(tmp, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())


def copy_file_atomic(src, dst) -> None:
    """Copy `src` over `dst` the same way: old file or new file, never half."""
    target = Path(dst)
    with _staged_path(target) as tmp:
        shutil.copyfile(src, tmp)
