#!/usr/bin/env python3
"""
hook 安装路径守门测试：注册的命令必须真的能跑。

对应 2026-11-27 review 的 C2 / C3：
  - C2 生成的是 `python <path>`，本机没有 `python` 这个命令；
  - C3 hook 写 `~/.claude/settings.json` 时是直接覆写，崩在中间就把用户的配置写坏。

这里不去断言「代码里怎么拼字符串」，而是把注册出来的命令原样执行一次 ——
命令跑得起来、会话文件落得下去，才算装上。
跑：python3 -m unittest discover -s tests -v
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "para-memory" / "scripts"
SCRIPT = SCRIPTS / "save_chat_history.py"

sys.path.insert(0, str(SCRIPTS))
import atomic_io  # noqa: E402
import install_hooks  # noqa: E402


class InstallHooksTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="pm-hooks-"))
        self.hooks_dest = self.root / "hooks" / "para-memory"
        self.settings = self.root / "settings.json"
        self.settings.write_text(json.dumps({"hooks": {}}, indent=2), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def install(self):
        hooks_dest = install_hooks.copy_scripts(dest=self.hooks_dest)
        return install_hooks.register_hook(
            settings_file=self.settings, hooks_dest=hooks_dest
        )

    def commands(self):
        settings = json.loads(self.settings.read_text(encoding="utf-8"))
        found = []
        for event, entries in settings.get("hooks", {}).items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    found.append((event, hook.get("command", "")))
        return found

    def test_registered_command_uses_an_absolute_interpreter(self):
        self.install()
        commands = self.commands()
        self.assertTrue(commands, f"没有注册任何 hook：{self.settings.read_text()}")
        for event, command in commands:
            argv = shlex.split(command)
            self.assertGreaterEqual(len(argv), 2, f"{event}: {command!r}")
            interpreter = argv[0]
            self.assertTrue(
                os.path.isabs(interpreter),
                f"{event} 的解释器不是绝对路径（PATH 里没有就静默失败）：{command!r}",
            )
            self.assertEqual(
                interpreter,
                sys.executable,
                f"{event} 没用当前解释器：{command!r}",
            )

    def test_registered_command_actually_captures_a_session(self):
        """把注册出来的命令原样跑一次：rc=0 且会话文件落盘。"""
        self.install()
        commands = dict(self.commands())
        command = commands.get("SessionEnd") or next(iter(commands.values()))

        transcript = self.root / "transcript.jsonl"
        lines = [
            {
                "type": "user",
                "sessionId": "hookprobe-0001",
                "cwd": "/tmp/probe",
                "message": {
                    "content": [{"type": "text", "text": "第一条消息：这一条必须超过二十个字符，否则会被当成琐碎会话直接跳过"}]
                },
            },
            {
                "type": "assistant",
                "sessionId": "hookprobe-0001",
                "cwd": "/tmp/probe",
                "message": {
                    "content": [{"type": "text", "text": "第二条消息：同样超过二十个字符，凑够两轮才允许落盘"}]
                },
            },
        ]
        transcript.write_text(
            "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
            encoding="utf-8",
        )
        payload = json.dumps(
            {"transcript_path": str(transcript), "session_id": "hookprobe-0001"}
        )
        env = {**os.environ, "PARA_MEMORY_ROOT": str(self.root / "memory-root")}

        result = subprocess.run(
            command,
            shell=True,
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.root),
        )
        self.assertEqual(
            result.returncode,
            0,
            f"注册的命令跑不起来：{command!r}\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        sessions = sorted((self.root / "memory-root" / "memory").glob("*.md"))
        self.assertEqual(
            len(sessions), 1, f"命令跑完了但没有会话文件：{result.stderr}"
        )

    def test_helper_module_is_copied_next_to_the_hook(self):
        install_hooks.copy_scripts(dest=self.hooks_dest)
        self.assertTrue((self.hooks_dest / "save_chat_history.py").exists())
        self.assertTrue(
            (self.hooks_dest / "atomic_io.py").exists(),
            "hook 依赖的原子写模块没被复制，装完就 ImportError",
        )

    def test_rerun_does_not_duplicate_hook_entries(self):
        self.install()
        self.install()
        settings = json.loads(self.settings.read_text(encoding="utf-8"))
        for event, entries in settings["hooks"].items():
            self.assertEqual(len(entries), 1, f"{event} 重复注册了：{entries}")

    def test_a_throwaway_interpreter_is_flagged(self):
        """venv/临时目录里的解释器会在目录删掉后静默停摆：安装时要喊出来。"""
        venv = "/Users/xuhui/tmp/.venv/bin/python3"
        self.assertIn(
            "虚拟环境",
            install_hooks.interpreter_risk(venv, "/Users/xuhui/tmp/.venv", "/usr"),
        )
        self.assertIn(
            "临时目录",
            install_hooks.interpreter_risk("/var/folders/xx/T/py/bin/python3", "/a", "/a"),
        )
        self.assertEqual(
            install_hooks.interpreter_risk("/usr/bin/python3", "/usr", "/usr"), ""
        )

    def test_python_flag_overrides_the_interpreter(self):
        install_hooks.copy_scripts(dest=self.hooks_dest)
        install_hooks.register_hook(
            settings_file=self.settings,
            hooks_dest=self.hooks_dest,
            interpreter="/usr/bin/python3",
        )
        command = dict(self.commands())["SessionEnd"]
        self.assertEqual(shlex.split(command)[0], "/usr/bin/python3")

    def test_registering_before_copying_the_script_fails_loudly(self):
        with self.assertRaises(SystemExit) as caught:
            install_hooks.register_hook(
                settings_file=self.settings, hooks_dest=self.hooks_dest
            )
        self.assertIn("不存在", str(caught.exception))

    def test_settings_write_is_atomic(self):
        original = self.settings.read_text(encoding="utf-8")
        with mock.patch.object(
            atomic_io.os, "replace", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                self.install()

        self.assertEqual(
            self.settings.read_text(encoding="utf-8"),
            original,
            "写 settings.json 中途失败，磁盘上应该还是上一版",
        )
        json.loads(self.settings.read_text(encoding="utf-8"))
        leftovers = sorted(p.name for p in self.root.iterdir())
        self.assertEqual(
            leftovers, ["hooks", "settings.json"], f"留下临时文件：{leftovers}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
