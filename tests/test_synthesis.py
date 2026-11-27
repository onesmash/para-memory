#!/usr/bin/env python3
"""
合成路径守门测试：索引没更新，就不许打印「完成」。

对应 2026-11-27 review 的 C4 / C5 / C6 / C7：
  - C4 `qmd embed` 被外面套了 600 秒硬超时（真实速度 ≈2 s/chunk，只够 ~301 chunk）
  - C5 `update_qmd_index()` 的返回值被丢掉，失败也打印 `✓ Synthesis complete!` 且 rc=0
  - C6 安装提示还是 `bun install -g github:tobi/qmd`（今天只走上游 npm 包）
  - C7 `summary.md` 用 `write_text` 直覆写，不是原子写

这里用一个假的 `qmd` 记录被调用参数、按需失败，再从磁盘和退出码两头验收。
跑：python3 -m unittest discover -s tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "para-memory" / "scripts"
SCRIPT = SCRIPTS / "weekly_synthesis.py"

sys.path.insert(0, str(SCRIPTS))
import atomic_io  # noqa: E402
import weekly_synthesis  # noqa: E402


class SynthesisTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="pm-synth-"))
        self.knowledge = self.root / "knowledge"
        self.entity = self.knowledge / "people" / "alice"
        self.entity.mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.call_log = self.root / "qmd-calls.log"
        self.today = date.today().isoformat()

        self.write_items()
        self.fake_qmd = self.make_qmd()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # -- fixtures --------------------------------------------------------
    def write_items(self):
        items = {
            "entity": "people/alice",
            "lastModified": "2026-11-27T00:00:00",
            "items": [
                {
                    "id": "alice-001",
                    "fact": "喜欢深烘焙咖啡",
                    "category": "preference",
                    "timestamp": "2026-11-20",
                    "source": "2026-11-20",
                    "status": "active",
                    "supersededBy": None,
                    "lastAccessed": self.today,
                    "accessCount": 3,
                },
                {
                    "id": "alice-002",
                    "fact": "2019 年住在柏林",
                    "category": "biographical",
                    "timestamp": "2019-05-01",
                    "source": "2019-05-01",
                    "status": "active",
                    "supersededBy": None,
                    "lastAccessed": "2019-06-01",
                    "accessCount": 0,
                },
            ],
        }
        (self.entity / "items.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def make_qmd(self, update_rc=0, embed_rc=0):
        path = self.bin / "qmd"
        path.write_text(
            "#!/bin/bash\n"
            f'printf \'%s\\n\' "$*" >> "{self.call_log}"\n'
            'if [ "$1" = "update" ] && [ "' + str(update_rc) + '" != "0" ]; then\n'
            '  echo "qmd update blew up" >&2\n'
            f"  exit {update_rc}\n"
            "fi\n"
            'if [ "$1" = "embed" ] && [ "' + str(embed_rc) + '" != "0" ]; then\n'
            '  echo "qmd embed blew up" >&2\n'
            f"  exit {embed_rc}\n"
            "fi\n"
            'if [ "$1" = "embed" ]; then\n'
            '  echo "✓ Done! Embedded 2 chunks"\n'
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def env(self, **overrides):
        env = {
            **os.environ,
            "PARA_MEMORY_ROOT": str(self.root),
            "QMD_BIN": str(self.fake_qmd),
            "QMD_CALL_LOG": str(self.call_log),
            "QMD_COLLECTIONS": "knowledge daily",
        }
        env.update(overrides)
        return env

    def run_synthesis(self, *args, **env_overrides):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.knowledge), *args],
            capture_output=True,
            text=True,
            env=self.env(**env_overrides),
            cwd=str(self.root),
        )

    def calls(self):
        if not self.call_log.exists():
            return []
        return [
            line.strip()
            for line in self.call_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    # -- C4: 每次 embed 只针对一个记忆集合，且不套外层硬超时 ------------
    def test_every_embed_call_is_scoped_to_one_collection(self):
        result = self.run_synthesis()
        self.assertEqual(result.returncode, 0, f"{result.stdout}\n{result.stderr}")

        embeds = [line for line in self.calls() if line.split()[0] == "embed"]
        self.assertEqual(
            len(embeds), 2, f"两个记忆集合应该各调用一次 embed，实际：{self.calls()}"
        )
        for line in embeds:
            parts = line.split()
            self.assertIn(
                "-c", parts, f"embed 没有限定集合（会去重排别人的索引）：{line}"
            )
            collections = [parts[i + 1] for i, p in enumerate(parts) if p == "-c"]
            self.assertEqual(
                len(collections), 1, f"embed 只认第一个 -c，别写多个：{line}"
            )
            self.assertIn(collections[0], ("knowledge", "daily"), line)

    def test_index_refresh_happens_before_embedding(self):
        self.run_synthesis()
        calls = self.calls()
        kinds = [line.split()[0] for line in calls]
        self.assertIn("update", kinds, f"新文件没进索引就直接 embed：{calls}")
        self.assertLess(kinds.index("update"), kinds.index("embed"), calls)

    def test_embed_carries_no_wall_clock_cap_by_default(self):
        """qmd 自己的 --timeout 到点会截断却照样 rc=0（实测 13s/3s 上限仍报 Done）。"""
        self.run_synthesis()
        embeds = [line for line in self.calls() if line.startswith("embed")]
        self.assertTrue(embeds, self.calls())
        for line in embeds:
            parts = line.split()
            self.assertIn("--timeout", parts, f"embed 没显式关掉截断：{line}")
            timeout_value = parts[parts.index("--timeout") + 1]
            self.assertEqual(
                timeout_value, "0", f"默认必须是不设上限（0 = no limit）：{line}"
            )

    def test_embed_timeout_can_be_raised_from_the_environment(self):
        self.run_synthesis(QMD_EMBED_TIMEOUT_MINUTES="45")
        embeds = [line for line in self.calls() if line.startswith("embed")]
        self.assertTrue(embeds, self.calls())
        for line in embeds:
            parts = line.split()
            self.assertEqual(parts[parts.index("--timeout") + 1], "45", line)

    def test_qmd_gets_its_own_bin_directory_on_path(self):
        """qmd 是 `#!/usr/bin/env node` 的 Node 脚本：只解析到 qmd 路径还不够，
        它旁边的 node 也得能找到 —— 否则 hook 环境里会 `env: node: No such file`。"""
        helper = self.bin / "qmd-node-helper"
        helper.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        helper.chmod(0o755)

        # 这个假 qmd 只按裸名字调用同目录的 helper：PATH 里没有那个目录就会失败
        qmd = self.bin / "qmd"
        qmd.write_text(
            "#!/bin/bash\n"
            'printf \'%s\\n\' "$*" >> "' + str(self.call_log) + '"\n'
            'if [ "$1" = "update" ]; then qmd-node-helper || { echo "env: node: No such file or directory" >&2; exit 127; }; fi\n'
            "exit 0\n",
            encoding="utf-8",
        )
        qmd.chmod(0o755)

        result = self.run_synthesis(PATH="/usr/bin:/bin")

        self.assertEqual(
            result.returncode,
            0,
            f"qmd 没能找到自己目录里的依赖（PATH 没带上它）：{result.stdout}",
        )
        self.assertIn("✓ Synthesis complete", result.stdout)

    # -- C5: 失败必须让进程失败，并说清索引没更新 ------------------------
    def test_failed_index_refresh_exits_nonzero(self):
        self.make_qmd(update_rc=3)
        result = self.run_synthesis()
        self.assertNotEqual(
            result.returncode, 0, f"索引刷新失败却报成功：{result.stdout}"
        )
        self.assertNotIn(
            "✓ Synthesis complete",
            result.stdout,
            "索引没更新，仍然打印了完成",
        )
        self.assertIn("索引未更新", result.stdout)

    def test_failed_embedding_exits_nonzero(self):
        self.make_qmd(embed_rc=2)
        result = self.run_synthesis()
        self.assertNotEqual(result.returncode, 0, f"embed 失败却报成功：{result.stdout}")
        self.assertIn("索引未更新", result.stdout)
        self.assertIn("qmd embed blew up", result.stdout + result.stderr)

    def test_missing_qmd_points_at_the_upstream_package(self):
        result = self.run_synthesis(
            QMD_BIN=str(self.root / "does-not-exist"),
            PATH="/usr/bin:/bin",
        )
        self.assertNotEqual(result.returncode, 0, f"qmd 不在却报成功：{result.stdout}")
        self.assertIn(
            "npm install -g @tobilu/qmd",
            result.stdout,
            "缺 qmd 时没给出上游安装命令（npm install -g @tobilu/qmd）",
        )
        self.assertNotIn(
            "bun install", result.stdout, "缺 qmd 时的安装提示还在用 bun（今天只走上游 npm 包）"
        )
        self.assertIn("索引未更新", result.stdout)

    def test_skip_qmd_is_an_explicit_degradation(self):
        result = self.run_synthesis("--skip-qmd")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [], f"--skip-qmd 还是调用了 qmd：{self.calls()}")
        self.assertIn("Skipped QMD update", result.stdout)

    # -- 一个坏实体 / 旧格式 summary / 索引状态 --------------------------
    def test_one_broken_items_json_does_not_stop_the_other_entities(self):
        broken = self.knowledge / "people" / "broken"
        broken.mkdir(parents=True)
        # 半写的 JSON：手编或崩溃时最常见的样子
        (broken / "items.json").write_text(
            '{"entity": "people/broken", "items": [', encoding="utf-8"
        )

        result = self.run_synthesis()

        self.assertNotEqual(
            result.returncode, 0, f"有实体写不出来却报成功：{result.stdout}"
        )
        self.assertIn("broken", result.stdout, "坏实体没有被点名")
        self.assertIn("个实体没有写出 summary", result.stdout)
        self.assertTrue(
            (self.entity / "summary.md").exists(),
            "一个坏 items.json 让好实体也没了 summary",
        )

    def test_a_summary_without_markers_is_rebuilt_not_carried_over(self):
        summary = self.entity / "summary.md"
        summary.write_text(
            "OLD LEGACY LINE：这一行属于旧格式，必须被清掉\n", encoding="utf-8"
        )

        weekly_synthesis.regenerate_summary(self.entity)

        text = summary.read_text(encoding="utf-8")
        self.assertNotIn(
            "OLD LEGACY LINE", text, "旧格式 summary 被整份当成 overview 保留了下来"
        )
        self.assertIn("## Hot Facts", text)

    def test_a_hand_written_overview_survives_regeneration(self):
        summary = self.entity / "summary.md"
        summary.write_text(
            "# Alice\n\n## Overview\n\n负责支付链路。\n\n## Hot Facts\n\n- 旧条目\n",
            encoding="utf-8",
        )

        weekly_synthesis.regenerate_summary(self.entity)

        text = summary.read_text(encoding="utf-8")
        self.assertIn("负责支付链路。", text, "手写的 Overview 被冲掉了")
        self.assertNotIn("旧条目", text, "旧的热点条目没被重建")

    def test_a_code_fence_inside_the_overview_survives(self):
        """Overview 里的围栏代码块含 `## ` 行时，不许把截取点切进围栏中间。"""
        summary = self.entity / "summary.md"
        summary.write_text(
            "# Alice\n\n## Overview\n\n说明：\n\n```md\n## 这一行在围栏里，不是小节\n"
            "kept?\n```\n\n## My Notes\n\n手写备注也要保住。\n\n## Hot Facts\n\n- 旧条目\n",
            encoding="utf-8",
        )

        weekly_synthesis.regenerate_summary(self.entity)

        text = summary.read_text(encoding="utf-8")
        self.assertIn(
            "## 这一行在围栏里，不是小节", text, "围栏里的 ## 行被当成了小节边界"
        )
        self.assertIn("kept?", text, "围栏后半被静默丢弃")
        self.assertIn("手写备注也要保住。", text, "手写小节被生成器吞掉了")
        self.assertNotIn("旧条目", text)

    def test_index_status_is_machine_readable(self):
        """rc 只有 0/1；调用方要区分「跳过」「已更新」「失败」得有一个 stderr 标记。"""
        self.assertIn("index=updated", self.run_synthesis().stderr)

        skipped = self.run_synthesis("--skip-qmd")
        self.assertEqual(skipped.returncode, 0, skipped.stderr)
        self.assertIn("index=skipped", skipped.stderr)

        self.make_qmd(embed_rc=2)
        failed = self.run_synthesis()
        self.assertIn("index=failed", failed.stderr)

    # -- C7: summary.md 原子写 -------------------------------------------
    def test_summary_lists_hot_facts_and_hides_cold_ones(self):
        hot, warm, cold = weekly_synthesis.regenerate_summary(self.entity)
        self.assertEqual((hot, warm, cold), (1, 0, 1))
        text = (self.entity / "summary.md").read_text(encoding="utf-8")
        self.assertIn("喜欢深烘焙咖啡", text)
        self.assertNotIn("柏林", text, "冷事实不该进 summary")

    def test_crash_during_summary_write_keeps_the_previous_version(self):
        summary = self.entity / "summary.md"
        summary.write_text("OLD SUMMARY", encoding="utf-8")

        with mock.patch.object(
            atomic_io.os, "replace", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                weekly_synthesis.regenerate_summary(self.entity)

        self.assertEqual(
            summary.read_text(encoding="utf-8"),
            "OLD SUMMARY",
            "写一半就崩，磁盘上应该还是上一版 —— 不是半截新内容",
        )
        leftovers = sorted(p.name for p in self.entity.iterdir())
        self.assertEqual(
            leftovers,
            ["items.json", "summary.md"],
            f"原子写失败后留下了临时文件：{leftovers}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
