#!/usr/bin/env python3
"""
查询侧脚本的守门测试：空结果不许伪装成故障。

起因（README「Known limits」里记过的一条）：`search_timeline.sh keyword` 在零命中时
被 `set -e` 下的 `grep` 带成 exit 1，调用方分不清「查完了没有」和「store 坏了」。
修法是把零命中显式写成 0 并说明「没有匹配」，本文件就是它的守门测试。

跑：python3 -m unittest discover -s tests -v
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH = REPO_ROOT / "skills" / "para-memory-query" / "scripts" / "search_timeline.sh"


class TimelineSearchExitCodes(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="para-timeline-"))
        (self.root / "memory").mkdir()
        (self.root / "memory" / "2026-11-01.md").write_text(
            "# 2026-11-01\n\nhello world\nsecond line\n", encoding="utf-8"
        )
        self.env = {**os.environ, "PARA_MEMORY_ROOT": str(self.root)}

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def run_search(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SEARCH), *args],
            capture_output=True,
            text=True,
            env=self.env,
        )

    def test_keyword_without_matches_exits_zero(self) -> None:
        result = self.run_search("keyword", "not-in-any-note")
        self.assertEqual(result.returncode, 0, f"零命中必须 exit 0，实际 {result.returncode}：{result.stderr}")
        self.assertIn("No matches found", result.stdout)

    def test_keyword_with_matches_exits_zero_and_prints_line(self) -> None:
        result = self.run_search("keyword", "hello")
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello world", result.stdout)
        self.assertIn("2026-11-01.md", result.stdout)

    def test_keyword_starting_with_dash_is_treated_as_pattern(self) -> None:
        result = self.run_search("keyword", "-n")
        self.assertEqual(result.returncode, 0, f"以 - 开头的关键词不许被当成选项：{result.stderr}")
        self.assertNotIn("option", result.stderr.lower())

    def test_date_without_note_keeps_exit_one(self) -> None:
        result = self.run_search("date", "1999-01-01")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No notes found", result.stdout)

    def test_unknown_mode_is_a_usage_error(self) -> None:
        result = self.run_search("nonsense")
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
