#!/usr/bin/env python3
"""
破坏变体回归：每条修法都要能被「退回旧写法」弄红，而且红在点名的那条断言上。

为什么要有这个文件：`python3 -m unittest discover -s tests` 全绿只证明「现在是绿的」，
不证明这些测试有分辨力。把每处修法单独退回旧写法、看对应测试按名字报红，才知道
测试真的盯着这件事。

隔离方式：变体跑在一个 `git worktree` 临时副本里，**不碰工作区**。上一版的实现在原地
打补丁再在 finally 里还原，被 kill -9 打断时仓库会留在被破坏的状态；临时副本没有这个
窗口（最坏是一次 `git worktree prune`）。

因此变体作用于 **HEAD**：先提交再跑。工作区有未提交改动时会打印提示（不阻止）。

跑：python3 tests/destruct_variants.py          （全部通过 exit 0，否则 exit 1）
也可以指定其中几条：python3 tests/destruct_variants.py C8 C7
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

CAPTURE = "skills/para-memory/scripts/save_chat_history.py"
SYNTHESIS = "skills/para-memory/scripts/weekly_synthesis.py"
HOOKS = "skills/para-memory/scripts/install_hooks.py"
ATOMIC = "skills/para-memory/scripts/atomic_io.py"
TIMELINE = "skills/para-memory-query/scripts/search_timeline.sh"

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
        "id": "P1",
        "why": "会话归属退回「按文件名前缀」——前缀相同的两个会话互相覆盖",
        "file": CAPTURE,
        "old": "            if file_owner(path) == session_id:",
        "new": "            if True:",
        "test": "tests.test_capture_path.CapturePathTest.test_two_sessions_sharing_a_filename_prefix_keep_separate_files",
        "expect": "两个不同会话被并成一个文件",
    },
    {
        "id": "P2-txt",
        "why": "txt 分支退回自己拼日期——跨天时又开一个文件",
        "file": CAPTURE,
        "old": (
            "        session_file = find_session_file(\n"
            "            sessions_dir,\n"
            '            "",\n'
            "            get_short_id(p.stem),\n"
            '            now.strftime("%Y-%m-%d"),\n'
            "            no_id_key=str(p.resolve()),\n"
            "        )\n"
        ),
        "new": (
            "        session_file = sessions_dir / "
            "f\"{now.strftime('%Y-%m-%d')}-{get_short_id(p.stem)}-session.md\"\n"
        ),
        "test": "tests.test_capture_path.CapturePathTest.test_txt_capture_follows_the_same_file_rule",
        "expect": "txt 分支在跨天时又开了一个文件",
    },
    {
        "id": "C2",
        "why": "去掉 __future__ annotations —— 3.9 上 import 期就 TypeError",
        "note": "需要本机存在 <3.10 的解释器才有分辨力（本机 /usr/bin/python3 = 3.9.6）",
        "file": CAPTURE,
        "old": "from __future__ import annotations\n\nimport hashlib",
        "new": "import json",
        "test": "tests.test_capture_path.CapturePathTest.test_hook_runs_under_the_oldest_python_available",
        "expect": "跑不起来",
    },
    {
        "id": "C3",
        "why": "注册命令退回裸 `python` —— 本机没有这个命令",
        "file": HOOKS,
        "old": '    return f"{shlex.quote(str(exe))} {shlex.quote(str(script_path))}"',
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
        "old": "    return 0 if index_ok else 1\n",
        "new": "    return 0 if True else 1\n",
        "test": "tests.test_synthesis.SynthesisTest.test_failed_index_refresh_exits_nonzero",
        "expect": "索引刷新失败却报成功",
    },
    {
        "id": "C6",
        "why": "安装提示退回 bun —— 与「只走上游 npm 包」冲突",
        "file": SYNTHESIS,
        "old": 'QMD_INSTALL_HINT = "npm install -g @tobilu/qmd"',
        "new": 'QMD_INSTALL_HINT = "bun install -g github:tobi/qmd"',
        "test": "tests.test_synthesis.SynthesisTest.test_missing_qmd_points_at_the_upstream_package",
        "expect": "没给出上游安装命令",
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
        "id": "P2-entity",
        "why": "坏 items.json 退回不兜底 —— 后面的实体全都没 summary",
        "file": SYNTHESIS,
        "old": "        except (OSError, ValueError, KeyError, TypeError) as exc:",
        "new": "        except ZeroDivisionError as exc:",
        "test": "tests.test_synthesis.SynthesisTest.test_one_broken_items_json_does_not_stop_the_other_entities",
        "expect": "坏实体没有被点名",
    },
    {
        "id": "P2-overview",
        "why": "overview 退回「按 ## Hot Facts 切一半」——旧格式 summary 整份复活",
        "file": SYNTHESIS,
        "old": '        overview = extract_overview(summary_path.read_text(encoding="utf-8"))',
        "new": (
            '        overview = summary_path.read_text(encoding="utf-8")'
            '.split("## Hot Facts", 1)[0].strip()'
        ),
        "test": "tests.test_synthesis.SynthesisTest.test_a_summary_without_markers_is_rebuilt_not_carried_over",
        "expect": "旧格式 summary 被整份当成 overview 保留了下来",
    },
    {
        "id": "P2-mode",
        "why": "原子写退回不保留权限 —— settings.json 被改成 0600",
        "file": ATOMIC,
        "old": "    os.chmod(tmp, _target_mode(target))\n    os.replace(tmp, target)",
        "new": "    os.replace(tmp, target)",
        "test": "tests.test_atomic_io.AtomicWrites.test_an_existing_file_keeps_its_mode",
        "expect": "原子写把文件权限改成了 mkstemp 的 0600",
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
    {
        "id": "P2-date-check",
        "why": "date 退回不校验格式 —— 短日期漏到 20 号",
        "file": TIMELINE,
        "old": (
            '        if ! [[ "$DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then\n'
            '            echo "Invalid date: ${DATE}（需要 YYYY-MM-DD）" >&2\n'
            "            exit 1\n"
            "        fi\n"
        ),
        "new": "        true\n",
        "test": "tests.test_query_scripts.TimelineSearchExitCodes.test_date_mode_rejects_a_partial_date",
        "expect": "二十号的会话",
    },
    {
        "id": "P2-keyword-store",
        "why": "keyword 退回把 grep rc>=2 当零命中 —— store 坏了报成「没有匹配」",
        "file": TIMELINE,
        "old": '        require_store\n        echo "Searching for keyword: $KEYWORD"',
        "new": '        echo "Searching for keyword: $KEYWORD"',
        "test": "tests.test_query_scripts.TimelineSearchExitCodes.test_keyword_against_a_missing_store_is_not_reported_as_no_match",
        "expect": "目录不存在时必须 exit 2",
    },
    {
        "id": "P1-txt-owner",
        "why": "无 id 的 txt 退回 `candidates[0]` —— 整份覆写别人的会话文件",
        "file": CAPTURE,
        "old": (
            "    for path in candidates:\n"
            "        if not file_owner(path):\n"
            "            return path\n"
            "    if file_owner(default):\n"
            "        return _disambiguated(default, no_id_key or short_id)\n"
            "    return default\n"
        ),
        "new": "    return candidates[0]\n",
        "test": "tests.test_capture_path.CapturePathTest.test_txt_capture_never_overwrites_a_file_that_belongs_to_a_session",
        "expect": "无 id 的 txt 捕获把另一个会话的文件整份覆盖了",
    },
    {
        "id": "P2-overview-fence",
        "why": "overview 退回正则截到第一个 `## ` —— 围栏里的行和手写小节被吞",
        "file": SYNTHESIS,
        "old": (
            "    prefix_lines = []\n"
            "    for line, in_fence in _unfenced_scan(content):\n"
            "        if not in_fence and line.strip() in GENERATED_HEADINGS:\n"
            "            break\n"
            "        prefix_lines.append(line)\n"
            "\n"
            '    prefix = "\\n".join(prefix_lines).strip()\n'
        ),
        "new": (
            "    import re as _re\n"
            '    _m = _re.search(r"^## Overview[ \\t]*$\\n(.*?)(?=^## |\\Z)", content,'
            " _re.MULTILINE | _re.DOTALL)\n"
            '    prefix = f"## Overview\\n\\n{_m.group(1).strip()}" if _m else ""\n'
        ),
        "test": "tests.test_synthesis.SynthesisTest.test_a_code_fence_inside_the_overview_survives",
        "expect": "围栏里的 ## 行被当成了小节边界",
    },
    {
        "id": "P3-read-window",
        "why": "身份行读取退回按字节截 4096 —— 长 slug 把 `**Session:**` 挤出窗口",
        "file": CAPTURE,
        "old": (
            "    lines = []\n"
            '    with path.open("r", encoding="utf-8", errors="replace") as handle:\n'
            "        for _ in range(max_lines):\n"
            "            line = handle.readline(65536)\n"
            "            if not line:\n"
            "                break\n"
            "            lines.append(line)\n"
            '    return "".join(lines)\n'
        ),
        "new": (
            '    with path.open("r", encoding="utf-8", errors="replace") as handle:\n'
            "        return handle.read(4096)\n"
        ),
        "test": "tests.test_capture_path.CapturePathTest.test_a_very_long_slug_does_not_hide_the_identity_line",
        "expect": "超长 slug 把身份行挤出了读取窗口",
    },
    {
        "id": "P3-bash32",
        "why": "变量退回不加大括号且紧贴全角括号 —— bash 3.2 吞字节",
        "file": TIMELINE,
        "old": 'echo "Invalid date: ${DATE}（需要 YYYY-MM-DD）" >&2',
        "new": 'echo "Invalid date: $DATE（需要 YYYY-MM-DD）" >&2',
        "test": "tests.test_shell_hygiene.ShellScripts.test_variables_are_braced_before_multibyte_text",
        "expect": "改成 ${VAR}",
    },
]


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)


def run_variant(variant: dict, worktree: Path) -> dict:
    path = worktree / variant["file"]
    original = path.read_text(encoding="utf-8")
    if variant["old"] not in original:
        return {
            "id": variant["id"],
            "red": False,
            "matched": False,
            "why": f"锚点已不在 {variant['file']} 里（代码变了，变体过期）",
        }

    path.write_text(original.replace(variant["old"], variant["new"], 1), encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", variant["test"]],
            cwd=str(worktree),
            capture_output=True,
            text=True,
        )
    finally:
        # 副本是抛弃式的，还原只是为了下一条变体从干净状态开始
        path.write_text(original, encoding="utf-8")

    output = result.stdout + result.stderr
    return {
        "id": variant["id"],
        "red": result.returncode != 0,
        "matched": variant["expect"] in output,
        "why": variant["why"],
        "note": variant.get("note", ""),
        "output": output,
    }


def main(argv: list[str]) -> int:
    wanted = set(argv[1:])
    selected = [v for v in VARIANTS if not wanted or v["id"] in wanted]
    if not selected:
        print(f"没有匹配的变体：{sorted(wanted)}")
        return 2

    dirty = git("status", "--porcelain").stdout.strip()
    if dirty:
        print("注意：工作区有未提交改动；变体作用于 HEAD，不是磁盘上的版本。\n")

    sandbox = Path(tempfile.mkdtemp(prefix="pm-destruct-"))
    worktree = sandbox / "repo"
    add = git("worktree", "add", "--detach", str(worktree), "HEAD")
    if add.returncode != 0:
        print(f"未判定：建不了临时 worktree（{add.stderr.strip()}）")
        return 2

    try:
        results = [run_variant(v, worktree) for v in selected]
    finally:
        git("worktree", "remove", "--force", str(worktree))
        git("worktree", "prune")

    failed = 0
    for result in results:
        ok = result["red"] and result["matched"]
        failed += 0 if ok else 1
        verdict = "PASS" if ok else "FAIL"
        note = f"  [{result['note']}]" if result.get("note") else ""
        print(
            f"{verdict}  {result['id']:<14}  red={result['red']!s:<5} "
            f"按名报红={result['matched']!s:<5}  {result['why']}{note}"
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
