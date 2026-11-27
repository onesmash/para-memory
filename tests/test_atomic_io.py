#!/usr/bin/env python3
"""
原子写的两条容易被忽略的性质：**权限不被悄悄改掉**，**不留临时文件**。

`mkstemp` 建出来的文件是 0600，直接 rename 到目标上会把 `settings.json`、共享的
`summary.md` 的权限一起收窄 —— 内容对了，语义变了。这条由机器守。

跑：python3 -m unittest discover -s tests -v
"""

import os
import stat
import tempfile
import unittest
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "para-memory" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import atomic_io  # noqa: E402


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class AtomicWrites(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="pm-atomic-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_an_existing_file_keeps_its_mode(self) -> None:
        target = self.root / "settings.json"
        target.write_text("old", encoding="utf-8")
        target.chmod(0o644)

        atomic_io.write_text_atomic(target, "new")

        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assertEqual(
            mode_of(target), 0o644, "原子写把文件权限改成了 mkstemp 的 0600"
        )

    def test_a_new_file_gets_the_umask_default(self) -> None:
        umask = os.umask(0)
        os.umask(umask)
        target = self.root / "fresh.md"

        atomic_io.write_text_atomic(target, "hello")

        self.assertEqual(mode_of(target), 0o666 & ~umask)

    def test_no_temp_files_survive_a_successful_write(self) -> None:
        target = self.root / "note.md"
        for text in ("one", "two", "three"):
            atomic_io.write_text_atomic(target, text)

        self.assertEqual(
            sorted(p.name for p in self.root.iterdir()),
            ["note.md"],
            "成功路径留下了临时文件",
        )
        self.assertEqual(target.read_text(encoding="utf-8"), "three")

    def test_copy_keeps_the_mode_of_the_target(self) -> None:
        src = self.root / "src.txt"
        src.write_text("payload", encoding="utf-8")
        src.chmod(0o600)
        dst = self.root / "dst.txt"
        dst.write_text("old", encoding="utf-8")
        dst.chmod(0o644)

        atomic_io.copy_file_atomic(src, dst)

        self.assertEqual(dst.read_text(encoding="utf-8"), "payload")
        self.assertEqual(mode_of(dst), 0o644)
        self.assertEqual(
            sorted(p.name for p in self.root.iterdir()), ["dst.txt", "src.txt"]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
