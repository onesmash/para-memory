#!/bin/bash
# para-memory 写入路径不变量的**一条命令重跑**入口。
#
# 退出码三态：
#   0 = 正确版守住（statechart rc 0）+ 两个破坏变体各自报红（rc 1）+ 守门测试全绿
#   1 = 与预期不符（谁没按预期红/绿，会点名）
#   2 = 未判定（工具链缺失：node / statechart / java / tla2tools / python3）
#
# 环境变量一律用私有前缀（PM_*），不读宿主/CI 里可能已占用的 JAVA、TLA2TOOLS、NODE_BIN：
#   PM_NODE_BIN      node 所在目录（默认 /usr/local/bin）
#   PM_SC            statechart 可执行文件
#   PM_JAVA          java 可执行文件
#   PM_TLA2TOOLS     tla2tools.jar
#   PM_PYTHON        python3
#
# 用法：bash spec/run.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

PM_NODE_BIN="${PM_NODE_BIN:-/usr/local/bin}"
PM_SC="${PM_SC:-$HOME/.agents/skills/statechart/scripts/statechart}"
PM_JAVA="${PM_JAVA:-/usr/bin/java}"
PM_TLA2TOOLS="${PM_TLA2TOOLS:-$HOME/tools/tla/tla2tools.jar}"
PM_PYTHON="${PM_PYTHON:-python3}"

PATH="$PM_NODE_BIN:$PATH"
export PATH

missing=0
command -v node >/dev/null 2>&1 || { echo "未判定：找不到 node（设 PM_NODE_BIN=<目录>）" >&2; missing=1; }
[ -x "$PM_SC" ]        || { echo "未判定：找不到 statechart（设 PM_SC=<路径>）" >&2; missing=1; }
[ -x "$PM_JAVA" ]      || { echo "未判定：找不到 java（设 PM_JAVA=<路径>）" >&2; missing=1; }
[ -r "$PM_TLA2TOOLS" ] || { echo "未判定：找不到 tla2tools.jar（设 PM_TLA2TOOLS=<路径>）" >&2; missing=1; }
command -v "$PM_PYTHON" >/dev/null 2>&1 || { echo "未判定：找不到 python3（设 PM_PYTHON=<路径>）" >&2; missing=1; }
[ "$missing" = "0" ] || exit 2

# 模型拷进临时目录跑，仓库里的 spec/ 保持只读
WORK="$(mktemp -d "${TMPDIR:-/tmp}/pm-spec.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM
cp "$HERE"/*.tla "$HERE"/*.cfg "$WORK"/
cd "$WORK" || exit 2

fail=0
for model in ParaMemory ParaMemoryLostUpdate ParaMemoryPartial; do
  JAVA="$PM_JAVA" TLA2TOOLS="$PM_TLA2TOOLS" \
    "$PM_SC" "$model.tla" --config "$model.cfg" --out "out-$model/" > "$model.log" 2>&1
  rc=$?
  case "$model" in
    ParaMemory)           want=0 ; label="正确版（两条性质都守住）" ;;
    ParaMemoryLostUpdate) want=1 ; label="破坏变体 A（无锁快照覆盖 → NoLostUpdate）" ;;
    ParaMemoryPartial)    want=1 ; label="破坏变体 B（两次落盘 + 崩溃 → AtomicSupersede）" ;;
  esac
  if [ "$rc" = "$want" ]; then
    echo "PASS  ${label}：rc=${rc}"
  else
    echo "FAIL  ${label}：rc=${rc}（预期 ${want}）" >&2
    tail -5 "$model.log" >&2
    fail=1
  fi
done

# 守门测试：S2 的反例回放 + S3 的绿
cd "$REPO" || exit 2
if "$PM_PYTHON" -m unittest discover -s tests > "$WORK/unit.log" 2>&1; then
  echo "PASS  守门测试：python3 -m unittest discover -s tests"
else
  echo "FAIL  守门测试（见下）" >&2
  tail -20 "$WORK/unit.log" >&2
  fail=1
fi

if [ "$fail" = "0" ]; then
  echo "PASS  para-memory 写入路径：两条性质守住，两个破坏变体各自报红"
  exit 0
fi
exit 1
