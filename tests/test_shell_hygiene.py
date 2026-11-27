#!/usr/bin/env python3
"""
shell 脚本的两条硬约束，由机器守，不靠记性。

1. 本机 `/bin/bash` 是 macOS 自带的 3.2：`$VAR` **紧贴**多字节字符（中文、全角括号）时，
   解析器会把多字节字符当成变量名的一部分，吞掉一个字节。实测
   `echo "Invalid date: $DATE（需要…）"` 的 stderr 少了 `EF`，只剩 `bc88`，Python 侧直接
   UnicodeDecodeError。一律写 `${VAR}`。
2. 语法错必须现在死：`bash -n` 不过的脚本不该等到用户手里才炸。

跑：python3 -m unittest discover -s tests -v
"""

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEDULE_DIRS = [
    REPO_ROOT / "skills" / "para-memory" / "scripts",
    REPO_ROOT / "skills" / "para-memory-query" / "scripts",
]
SHELL_SCRIPTS = sorted(
    path for directory in SCHEDULE_DIRS for path in directory.glob("*.sh")
)

# `$NAME` 后面紧跟一个非 ASCII 字节 —— bash 3.2 会把它并进变量名
UNBRACED_THEN_MULTIBYTE = re.compile(r"(?<!\$)\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]")


class ShellScripts(unittest.TestCase):
    def test_there_is_at_least_one_script_to_check(self):
        # 空输入集上的检查必然通过 —— 那不叫验证
        self.assertTrue(SHELL_SCRIPTS, "一个 .sh 都没找到，这条检查什么也没证明")

    def test_variables_are_braced_before_multibyte_text(self):
        offenders = []
        for path in SHELL_SCRIPTS:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if UNBRACED_THEN_MULTIBYTE.search(line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "bash 3.2 下这些行的变量会被多字节字符吞掉一个字节，改成 ${VAR}：\n"
            + "\n".join(offenders),
        )

    def test_every_script_parses(self):
        for path in SHELL_SCRIPTS:
            result = subprocess.run(
                ["bash", "-n", str(path)], capture_output=True, text=True
            )
            self.assertEqual(
                result.returncode, 0, f"{path.name} 语法不过：{result.stderr}"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
