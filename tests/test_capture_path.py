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
SCRIPTS = REPO_ROOT / "skills" / "para-memory" / "scripts"
SCRIPT = SCRIPTS / "save_chat_history.py"

SESSION_ID = "sess0001-aaaa-bbbb"


def entry(role, text, tool=None, session_id=SESSION_ID):
    """Build a transcript line shaped like Claude Code's JSONL."""
    item = {
        "type": role,
        "sessionId": session_id,
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

    def run_hook(self, interpreter=None, session_id=SESSION_ID, transcript=None):
        payload = {"transcript_path": str(transcript or self.transcript)}
        if session_id:
            payload["session_id"] = session_id
        payload = json.dumps(payload)
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

    # -- P1：文件名前缀相同 ≠ 同一个会话 --------------------------------
    def test_two_sessions_sharing_a_filename_prefix_keep_separate_files(self):
        """`ab-12345…` 与 `ab.12345…` 净化后都变 `ab-123`：不许后到的整份覆盖先到的。"""
        sys.path.insert(0, str(SCRIPTS))
        import save_chat_history  # 按需导入：本文件在 3.9 下也必须能被收集

        first_id, second_id = "ab-12345aaaa", "ab.12345bbbb"
        self.assertEqual(
            save_chat_history.get_short_id(first_id),
            save_chat_history.get_short_id(second_id),
            "前提不成立（这两个 id 前缀已不同），这条测试没有意义了",
        )

        self.write_transcript([
            entry("user", "会话一的开场白：这一段只属于第一个会话，长度足够", session_id=first_id),
            entry("assistant", "会话一的回复：同样只属于第一个会话，长度足够", session_id=first_id),
        ])
        self.assertEqual(self.run_hook(session_id=first_id).returncode, 0)

        self.write_transcript([
            entry("user", "会话二的开场白：另一段对话，必须单独落一个文件", session_id=second_id),
            entry("assistant", "会话二的回复：另一段对话的后半，长度同样足够", session_id=second_id),
        ])
        self.assertEqual(self.run_hook(session_id=second_id).returncode, 0)

        texts = [f.read_text(encoding="utf-8") for f in self.session_files()]
        self.assertEqual(
            len(texts), 2, f"两个不同会话被并成一个文件：{[f.name for f in self.session_files()]}"
        )
        self.assertTrue(any("会话一的开场白" in t for t in texts), "会话一被覆盖了")
        self.assertTrue(any("会话二的开场白" in t for t in texts), "会话二没落盘")

    def test_a_session_started_on_an_earlier_day_stays_in_its_file(self):
        """跨午夜：文件名是「开始那天」，重捕获必须回到同一个文件。"""
        self.sessions.mkdir(parents=True, exist_ok=True)
        earlier = self.sessions / "2025-01-01-sess0001-session.md"
        earlier.write_text(
            f"# Session: demo\n**Session:** {SESSION_ID}\n**Date:** 2025-01-01\n"
            f"**Started:** 23:50\n\n---\n\n旧内容\n",
            encoding="utf-8",
        )
        self.write_transcript(FIRST_TURNS)
        self.capture()

        self.assertEqual(
            [f.name for f in self.session_files()],
            ["2025-01-01-sess0001-session.md"],
            "跨午夜后又开了一个新文件 —— 同一段对话被拆成两份",
        )
        self.assertIn("第一条消息", earlier.read_text(encoding="utf-8"))

    def test_txt_capture_follows_the_same_file_rule(self):
        """`.txt` 分支不许自己拼日期：同一份 txt 跨天重捕获要回到原文件。"""
        self.sessions.mkdir(parents=True, exist_ok=True)
        earlier = self.sessions / "2025-01-01-chat-session.md"
        earlier.write_text("旧内容\n", encoding="utf-8")

        txt = self.root / "chat.txt"
        txt.write_text("今天的转录正文\n", encoding="utf-8")
        result = self.run_hook(transcript=txt, session_id=None)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [f.name for f in self.session_files()],
            ["2025-01-01-chat-session.md"],
            "txt 分支在跨天时又开了一个文件",
        )
        self.assertIn("今天的转录正文", earlier.read_text(encoding="utf-8"))

    def test_transcripts_without_a_session_id_do_not_merge(self):
        """没有 session id 时按 transcript 路径区分，不能都落进 `unknown`。"""
        self.sessions.mkdir(parents=True, exist_ok=True)
        for name in ("one", "two"):
            path = self.root / f"{name}.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "type": role,
                            "message": {
                                "content": [{"type": "text", "text": f"{name} 的{role}发言：这一句必须超过二十个字符，否则会被当成琐碎会话跳过"}]
                            },
                        },
                        ensure_ascii=False,
                    )
                    for role in ("user", "assistant")
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.run_hook(transcript=path, session_id=None)
            self.assertEqual(result.returncode, 0, result.stderr)

        names = [f.name for f in self.session_files()]
        self.assertEqual(len(names), 2, f"没有 session id 的两次捕获并成了一个文件：{names}")

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
