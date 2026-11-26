#!/bin/bash
# 可分离性实验：证明 P1 与 P2 是**两个**失败，不是一个「失败家族」。
#
# 4 种修法组合 × 2 条不变量 = 8 次 TLC。期望矩阵（关掉谁的修法，就只红谁）：
#
#   FixAtomic FixLock | AtomicSupersede NoLostUpdate
#   TRUE      TRUE    | 0               0
#   TRUE      FALSE   | 0               12
#   FALSE     TRUE    | 12              0
#   FALSE     FALSE   | 12              12
#
# 退出码：0 = 矩阵完全符合；1 = 不符（点名哪一格）；2 = 工具链缺失
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PM_JAVA="${PM_JAVA:-/usr/bin/java}"
PM_TLA2TOOLS="${PM_TLA2TOOLS:-$HOME/tools/tla/tla2tools.jar}"
[ -x "$PM_JAVA" ]      || { echo "未判定：找不到 java（设 PM_JAVA=<路径>）" >&2; exit 2; }
[ -r "$PM_TLA2TOOLS" ] || { echo "未判定：找不到 tla2tools.jar（设 PM_TLA2TOOLS=<路径>）" >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/pm-sep.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM
cp "$HERE"/ParaMemorySeparability.tla "$WORK"/
cd "$WORK" || exit 2

fail=0
for row in "AA TRUE TRUE 0 0" "AB TRUE FALSE 0 12" "BA FALSE TRUE 12 0" "BB FALSE FALSE 12 12"; do
  set -- $row
  name=$1; fa=$2; fl=$3; want_atomic=$4; want_lost=$5
  for pair in "AtomicSupersede $want_atomic" "NoLostUpdate $want_lost"; do
    set -- $pair
    inv=$1; want=$2
    printf 'CONSTANT\n    FixAtomic = %s\n    FixLock = %s\nSPECIFICATION Spec\nINVARIANT %s\n' \
      "$fa" "$fl" "$inv" > "$name-$inv.cfg"
    "$PM_JAVA" -XX:+UseParallelGC -cp "$PM_TLA2TOOLS" tlc2.TLC -workers 1 \
      -config "$name-$inv.cfg" ParaMemorySeparability.tla > "$name-$inv.log" 2>&1
    rc=$?
    if [ "$rc" = "$want" ]; then
      echo "PASS  ${name} FixAtomic=${fa} FixLock=${fl} ${inv} rc=${rc}"
    else
      echo "FAIL  ${name} FixAtomic=${fa} FixLock=${fl} ${inv} rc=${rc}（预期 ${want}）" >&2
      grep -E 'is violated|deadlock|Error' "$name-$inv.log" | head -3 >&2
      fail=1
    fi
  done
done

[ "$fail" = "0" ] || exit 1
echo "PASS  可分离：关掉 P1 的修法只红 AtomicSupersede，关掉 P2 的修法只红 NoLostUpdate"
exit 0
