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

    # --- C8：捕获写的是 `<date>-<shortid>-session.md`，date 模式必须认得出 ---
    def write_note(self, name: str, body: str) -> None:
        (self.root / "memory" / name).write_text(body, encoding="utf-8")

    def test_date_mode_reads_capture_files_for_that_day(self) -> None:
        self.write_note("2026-11-27-sess0001-session.md", "# Session: one\n\n第一条会话正文\n")
        self.write_note("2026-11-27-sess0002-session.md", "# Session: two\n\n第二条会话正文\n")

        result = self.run_search("date", "2026-11-27")

        self.assertEqual(
            result.returncode,
            0,
            f"按日期查不到当天的会话文件（捕获写的是 <date>-<id>-session.md）：{result.stdout}",
        )
        for needle in ("第一条会话正文", "第二条会话正文", "sess0001", "sess0002"):
            self.assertIn(needle, result.stdout, f"漏了 {needle}：{result.stdout}")

    def test_date_mode_still_reads_a_legacy_plain_date_file(self) -> None:
        result = self.run_search("date", "2026-11-01")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("hello world", result.stdout)

    def test_date_mode_does_not_leak_other_days(self) -> None:
        self.write_note("2026-11-28-sess0009-session.md", "别的一天的正文\n")
        result = self.run_search("date", "2026-11-27")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn("别的一天的正文", result.stdout)

    def test_range_mode_places_session_files_by_their_day(self) -> None:
        self.write_note("2026-11-15-sess0003-session.md", "月中那次会话\n")
        result = self.run_search("range", "2026-11-10", "2026-11-20")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("月中那次会话", result.stdout)
        self.assertNotIn("2026-11-27", result.stdout)

    def test_keyword_against_a_missing_store_is_not_reported_as_no_match(self) -> None:
        """目录被移动时 `grep` 返回 2；那必须报错，不能报成「没有匹配」。"""
        env = {**os.environ, "PARA_MEMORY_ROOT": str(self.root / "moved-away")}
        result = subprocess.run(
            ["bash", str(SEARCH), "keyword", "hello"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(
            result.returncode,
            2,
            f"目录不存在时必须 exit 2（否则 store 坏了会被报成没有匹配）；"
            f"rc={result.returncode}：{result.stdout}{result.stderr}",
        )
        self.assertNotIn("No matches found", result.stdout)
        self.assertIn("Memory store not found", result.stderr)

    def test_date_and_range_against_a_missing_store_also_exit_two(self) -> None:
        env = {**os.environ, "PARA_MEMORY_ROOT": str(self.root / "moved-away")}
        for args in (["date", "2026-11-27"], ["range", "2026-11-01", "2026-11-30"]):
            result = subprocess.run(
                ["bash", str(SEARCH), *args], capture_output=True, text=True, env=env
            )
            self.assertEqual(result.returncode, 2, f"{args}: {result.stdout}{result.stderr}")

    def test_date_mode_rejects_a_partial_date(self) -> None:
        """`2026-11-2` 当前缀会漏到 20 号：短日期是坏请求，不是前缀。"""
        self.write_note("2026-11-20-sess0005-session.md", "二十号的会话\n")
        result = self.run_search("date", "2026-11-2")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn("二十号的会话", result.stdout)
        self.assertIn("Invalid date", result.stderr)

    def test_date_mode_rejects_glob_metacharacters(self) -> None:
        result = self.run_search("date", "*")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn("hello world", result.stdout)

    def test_range_mode_ignores_files_that_are_not_dated(self) -> None:
        """memory/ 里可能出现 README 之类；它们不该被算进任何日期区间。"""
        self.write_note("MEMORY.md", "这一份不是按日期命名的\n")
        self.write_note("README.md", "这一份也不是\n")
        result = self.run_search("range", "2026-11-01", "2026-11-30")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("hello world", result.stdout)
        self.assertNotIn("不是按日期命名的", result.stdout)
        self.assertNotIn("这一份也不是", result.stdout)

    def test_unknown_mode_is_a_usage_error(self) -> None:
        result = self.run_search("nonsense")
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
