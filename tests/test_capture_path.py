#!/usr/bin/env python3
"""
捕获路径守门测试：一次会话只能存下第一轮，是缺陷不是设计。

对应 2026-11-27 review 的 C1：`save_chat_history.py` 在会话文件已存在时只重写
`**Last Updated:**` 一行，正文不重渲染 —— 于是第二次及以后的 transcript 全部丢失，
而日志还打印 "Updated session file"。

这里按 hook 的真实用法驱动：把 hook 输入写进 stdin、用子进程跑脚本、读落盘的 md。
跑：python3 -m unittest discover -s tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "para-memory" / "scripts" / "save_chat_history.py"
SESSION_ID = "sess0001-aaaa-bbbb"


def entry(role, text, tool=None):
    """Build a transcript line shaped like Claude Code's JSONL."""
    item = {
        "type": role,
        "sessionId": SESSION_ID,
        "cwd": "/tmp/demo-project",
        "slug": "demo-session",
    }
    blocks = [{"type": "text", "text": text}]
    if tool:
        blocks.append(
            {"type": "tool_use", "name": tool[0], "input": {"file_path": tool[1]}}
        )
    item["message"] = {"content": blocks}
    return item


FIRST_TURNS = [
    entry("user", "第一条消息：这条会话开头说了什么，足够长以免被当成琐碎会话"),
    entry("assistant", "第一条回复：同样足够长，让 trivial-session 判定不成立"),
]

MORE_TURNS = FIRST_TURNS + [
    entry("user", "用户第三条消息：这一段在第二次触发时才出现，必须落盘"),
    entry(
        "assistant",
        "第三条回复：并且带一次工具调用，用来验证头部也会跟着刷新",
        tool=("Write", "/tmp/demo-project/notes/new-file.md"),
    ),
]


def strip_timestamp(text):
    """Drop the only line that is allowed to change between identical runs."""
    return "\n".join(
        line for line in text.splitlines() if not line.startswith("**Last Updated:**")
    )


class CapturePathTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="pm-capture-"))
        self.transcript = self.root / "transcript.jsonl"
        self.sessions = self.root / "memory"
        self.env = {**os.environ, "PARA_MEMORY_ROOT": str(self.root)}

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # -- helpers ---------------------------------------------------------
    def write_transcript(self, entries):
        self.transcript.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
            encoding="utf-8",
        )

    def run_hook(self, interpreter=None):
        payload = json.dumps(
            {"transcript_path": str(self.transcript), "session_id": SESSION_ID}
        )
        return subprocess.run(
            [interpreter or sys.executable, str(SCRIPT)],
            input=payload,
            capture_output=True,
            text=True,
            env=self.env,
            cwd=str(self.root),
        )

    def session_files(self):
        return sorted(self.sessions.glob("*.md")) if self.sessions.exists() else []

    def capture(self):
        """Run the hook once and return the single session file's text."""
        result = self.run_hook()
        self.assertEqual(
            result.returncode, 0, f"hook 自己失败了：{result.stderr.strip()}"
        )
        files = self.session_files()
        self.assertEqual(len(files), 1, f"期望恰好一个会话文件，实际 {files}")
        return files[0].read_text(encoding="utf-8")

    # -- C1: 第二次触发必须带上新消息 ------------------------------------
    def test_second_capture_drops_nothing_from_the_first(self):
        self.write_transcript(FIRST_TURNS)
        first = self.capture()

        self.write_transcript(MORE_TURNS)
        second = self.capture()

        self.assertIn("第一条消息", second, "重渲染把上一轮的正文弄丢了")
        self.assertIn(
            "用户第三条消息",
            second,
            "第二次触发后正文里仍然没有新消息 —— 捕获只存了第一轮",
        )
        self.assertGreater(
            len(second.encode("utf-8")),
            len(first.encode("utf-8")),
            "文件没有变长，说明正文没有被重新渲染",
        )

    def test_recapture_of_an_unchanged_transcript_is_stable(self):
        self.write_transcript(MORE_TURNS)
        first = self.capture()
        second = self.capture()

        self.assertEqual(
            strip_timestamp(first),
            strip_timestamp(second),
            "同一份 transcript 跑两次，正文不一致 —— 操作不是幂等的",
        )
        self.assertEqual(
            len(self.session_files()), 1, "同一会话在两次触发后留下了两个文件"
        )

    def test_header_metadata_follows_the_transcript(self):
        self.write_transcript(FIRST_TURNS)
        first = self.capture()
        self.assertIn("**Tools:** —", first)

        self.write_transcript(MORE_TURNS)
        second = self.capture()
        self.assertIn("**Tools:** Write", second, "工具列表没有随 transcript 刷新")
        self.assertIn(
            "/tmp/demo-project/notes/new-file.md",
            second,
            "文件列表没有随 transcript 刷新",
        )

    def test_started_stamp_survives_recapture(self):
        self.write_transcript(FIRST_TURNS)
        first = self.capture()
        started = [
            line for line in first.splitlines() if line.startswith("**Started:**")
        ]
        self.assertEqual(len(started), 1, f"缺少 Started 行：{first[:200]}")

        self.write_transcript(MORE_TURNS)
        second = self.capture()
        self.assertIn(
            started[0], second, "重渲染把 Started 时间改掉了 —— 它记录的是会话开始"
        )

    def test_trivial_transcript_is_still_skipped(self):
        self.write_transcript([entry("user", "太短")])
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.session_files(), [], "琐碎会话不该落盘")

    # -- C2: 最老的解释器上也要能跑 --------------------------------------
    def test_hook_runs_under_the_oldest_python_available(self):
        """本机 /usr/bin/python3 是 3.9.6；脚本曾因 `dict | None` 在 import 期就 TypeError。"""
        candidates = ["/usr/bin/python3", "/usr/local/bin/python3", "python3"]
        available = []
        for path in candidates:
            try:
                probe = subprocess.run(
                    [path, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if probe.returncode != 0:
                continue
            try:
                version = tuple(int(part) for part in probe.stdout.strip().split("."))
            except ValueError:
                continue
            available.append((version, path))

        if not available:
            self.skipTest("找不到任何可用的 python3 解释器")
        version, path = min(available)
        if version >= (3, 10):
            self.skipTest(f"本机最老的解释器是 {path} {version}，测不到 3.9 路径")

        self.write_transcript(FIRST_TURNS)
        result = self.run_hook(interpreter=path)
        self.assertEqual(
            result.returncode,
            0,
            f"{path} ({version[0]}.{version[1]}) 跑不起来：{result.stderr.strip()}",
        )
        self.assertNotIn("TypeError", result.stderr)
        self.assertEqual(
            len(self.session_files()), 1, f"{path} 没有落盘任何会话文件"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
