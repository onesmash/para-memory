#!/usr/bin/env python3
"""
破坏变体回归：每条修法都要能被「退回旧写法」弄红，而且红在点名的那条断言上。

为什么要有这个文件：`python3 -m unittest discover -s tests` 全绿只证明「现在是绿的」，
不证明这些测试有分辨力。把每处修法单独退回旧写法、看对应测试按名字报红，才知道
测试真的盯着这件事。Lang 里的每一行都对应 2026-11-27 review 的一个 finding。

跑：python3 tests/destruct_variants.py          （全部通过 exit 0，否则 exit 1）
也可以指定其中几条：python3 tests/destruct_variants.py C8 C7
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "skills" / "para-memory" / "scripts"
QUERY = REPO / "skills" / "para-memory-query" / "scripts"

CAPTURE = SCRIPTS / "save_chat_history.py"
SYNTHESIS = SCRIPTS / "weekly_synthesis.py"
HOOKS = SCRIPTS / "install_hooks.py"
TIMELINE = QUERY / "search_timeline.sh"

VARIANTS = [
    {
        "id": "C1",
        "why": "捕获退回「只改时间戳」——正文不再重渲染",
        "file": CAPTURE,
        "old": (
            "    existed = session_file.exists()\n"
            "    day, started = today, current_time\n"
        ),
        "new": (
            "    existed = session_file.exists()\n"
            "    if existed:\n"
            "        stale = session_file.read_text(encoding='utf-8')\n"
            "        stale = re.sub(r'\\*\\*Last Updated:\\*\\*.*',\n"
            "                       f'**Last Updated:** {current_time}', stale)\n"
            "        session_file.write_text(stale, encoding='utf-8')\n"
            "        return\n"
            "    day, started = today, current_time\n"
        ),
        "test": "tests.test_capture_path.CapturePathTest.test_second_capture_drops_nothing_from_the_first",
        "expect": "第二次触发后正文里仍然没有新消息",
    },
    {
        "id": "C2",
        "why": "去掉 __future__ annotations —— 3.9 上 import 期就 TypeError",
        "file": CAPTURE,
        "old": "from __future__ import annotations\n\nimport json",
        "new": "import json",
        "test": "tests.test_capture_path.CapturePathTest.test_hook_runs_under_the_oldest_python_available",
        "expect": "跑不起来",
    },
    {
        "id": "C3",
        "why": "注册命令退回裸 `python` —— 本机没有这个命令",
        "file": HOOKS,
        "old": '    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))}"',
        "new": '    return f"python {script_path}"',
        "test": "tests.test_install_hooks.InstallHooksTest.test_registered_command_uses_an_absolute_interpreter",
        "expect": "的解释器不是绝对路径",
    },
    {
        "id": "C4",
        "why": "embed 退回不限集合 —— 会去重排用户别的索引",
        "file": SYNTHESIS,
        "old": 'binary, ["embed", "-c", collection, "--timeout", timeout]',
        "new": 'binary, ["embed", "--timeout", timeout]',
        "test": "tests.test_synthesis.SynthesisTest.test_every_embed_call_is_scoped_to_one_collection",
        "expect": "embed 没有限定集合",
    },
    {
        "id": "C4-t",
        "why": "embed 退回不传 --timeout —— qmd 自己的 30 分钟上限会静默截断",
        "file": SYNTHESIS,
        "old": 'binary, ["embed", "-c", collection, "--timeout", timeout]',
        "new": 'binary, ["embed", "-c", collection]',
        "test": "tests.test_synthesis.SynthesisTest.test_embed_carries_no_wall_clock_cap_by_default",
        "expect": "embed 没显式关掉截断",
    },
    {
        "id": "C9",
        "why": "qmd 子进程退回继承环境 PATH —— node 不在 PATH 上就 `env: node: No such file`",
        "file": SYNTHESIS,
        "old": (
            "    env = dict(os.environ)\n"
            '    env["PATH"] = str(Path(binary).parent) + os.pathsep + env.get("PATH", "")\n'
        ),
        "new": "    env = dict(os.environ)\n",
        "test": "tests.test_synthesis.SynthesisTest.test_qmd_gets_its_own_bin_directory_on_path",
        "expect": "qmd 没能找到自己目录里的依赖",
    },
    {
        "id": "C5",
        "why": "qmd 失败退回 rc=0 —— 索引没更新却说完成",
        "file": SYNTHESIS,
        "old": (
            '    print("  搜索到的仍是旧索引。修好 qmd 后重跑，或加 --skip-qmd 明确跳过。")\n'
            "    return 1\n"
        ),
        "new": (
            '    print("  搜索到的仍是旧索引。修好 qmd 后重跑，或加 --skip-qmd 明确跳过。")\n'
            "    return 0\n"
        ),
        "test": "tests.test_synthesis.SynthesisTest.test_failed_index_refresh_exits_nonzero",
        "expect": "索引刷新失败却报成功",
    },
    {
        "id": "C7",
        "why": "summary.md 退回 write_text —— 写一半崩就留下半截文件",
        "file": SYNTHESIS,
        "old": "    write_text_atomic(summary_path, summary_content)",
        "new": "    summary_path.write_text(summary_content)",
        "test": "tests.test_synthesis.SynthesisTest.test_crash_during_summary_write_keeps_the_previous_version",
        "expect": "OSError not raised",
    },
    {
        "id": "C8",
        "why": "date 模式退回精确 <date>.md —— 捕获写的会话文件全查不到",
        "file": TIMELINE,
        "old": '        files=("$DAILY_NOTES_DIR/$DATE"*.md)',
        "new": '        files=("$DAILY_NOTES_DIR/$DATE.md")',
        "test": "tests.test_query_scripts.TimelineSearchExitCodes.test_date_mode_reads_capture_files_for_that_day",
        "expect": "按日期查不到当天的会话文件",
    },
]

COLUMNS = ("id", "red", "matched", "why")


def run_variant(variant: dict) -> dict:
    path = variant["file"]
    original = path.read_text(encoding="utf-8")
    if variant["old"] not in original:
        return {
            "id": variant["id"],
            "red": False,
            "matched": False,
            "why": f"锚点已不在 {path.name} 里（代码变了，变体过期）",
        }

    patched = original.replace(variant["old"], variant["new"], 1)
    try:
        path.write_text(patched, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", variant["test"]],
            cwd=str(REPO),
            capture_output=True,
            text=True,
        )
    finally:
        path.write_text(original, encoding="utf-8")

    output = result.stdout + result.stderr
    went_red = result.returncode != 0
    matched = variant["expect"] in output
    return {
        "id": variant["id"],
        "red": went_red,
        "matched": matched,
        "why": variant["why"],
        "output": output,
    }


def main(argv: list[str]) -> int:
    wanted = set(argv[1:])
    selected = [v for v in VARIANTS if not wanted or v["id"] in wanted]
    if not selected:
        print(f"没有匹配的变体：{sorted(wanted)}")
        return 2

    results = [run_variant(v) for v in selected]

    failed = 0
    for result in results:
        ok = result["red"] and result["matched"]
        failed += 0 if ok else 1
        verdict = "PASS" if ok else "FAIL"
        print(
            f"{verdict}  {result['id']:<6}  red={result['red']!s:<5} "
            f"按名报红={result['matched']!s:<5}  {result['why']}"
        )
        if not ok:
            tail = "\n".join((result.get("output") or "").strip().splitlines()[-8:])
            print(f"        ↳ 实际输出尾部：\n{tail}")

    print()
    if failed:
        print(f"FAIL  {failed}/{len(results)} 个破坏变体没有按预期变红")
        return 1
    print(f"PASS  {len(results)}/{len(results)} 个破坏变体各自按名字红了")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
