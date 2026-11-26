---- MODULE ParaMemory ----
\* para-memory 写入路径：**目标设计**（每个实体一把锁 + 每次操作一次原子落盘）。
\*
\* 一个实体的 items.json，用标量表示（statechart 只吃枚举型状态变量）：
\*   f1 = 旧事实的状态（active / superseded）
\*   f2 = 取代它的新事实（absent / active）
\*   ptr = 旧事实的 supersededBy 指针（0 = 空，2 = 指向新事实）
\*   f3 / f4 = 两个并发 --add 各自要写的事实
\*   p1/p2 = 两个写者的位置；c1/c2 = 它们是否已经打印过成功
\*   lock = 0 空闲 / 1、2 被写者持有 / 3 被 supersede 持有
\*   sPC = supersede 的位置
EXTENDS Naturals

VARIABLES f1, f2, ptr, f3, f4, p1, p2, c1, c2, lock, sPC
vars == <<f1, f2, ptr, f3, f4, p1, p2, c1, c2, lock, sPC>>

Init ==
    /\ f1 = "active"  /\ f2 = "absent" /\ ptr = 0
    /\ f3 = "absent"  /\ f4 = "absent"
    /\ p1 = "read"    /\ p2 = "read"
    /\ c1 = "no"      /\ c2 = "no"
    /\ lock = 0       /\ sPC = "idle"

\* ---- 并发 --add：读与写在同一把锁里，写的时候直接改目标条目（没有快照覆盖）----
AddRead1 ==
    /\ p1 = "read" /\ lock = 0
    /\ lock' = 1 /\ p1' = "write"
    /\ UNCHANGED <<f1, f2, ptr, f3, f4, p2, c1, c2, sPC>>

AddCommit1 ==
    /\ p1 = "write" /\ lock = 1
    /\ f3' = "active" /\ c1' = "yes" /\ lock' = 0 /\ p1' = "done"
    /\ UNCHANGED <<f1, f2, ptr, f4, p2, c2, sPC>>

AddRead2 ==
    /\ p2 = "read" /\ lock = 0
    /\ lock' = 2 /\ p2' = "write"
    /\ UNCHANGED <<f1, f2, ptr, f3, f4, p1, c1, c2, sPC>>

AddCommit2 ==
    /\ p2 = "write" /\ lock = 2
    /\ f4' = "active" /\ c2' = "yes" /\ lock' = 0 /\ p2' = "done"
    /\ UNCHANGED <<f1, f2, ptr, f3, p1, c1, sPC>>

\* ---- supersede：两处改动一次落盘 ----
SupStart ==
    /\ sPC = "idle" /\ lock = 0
    /\ lock' = 3 /\ sPC' = "commit"
    /\ UNCHANGED <<f1, f2, ptr, f3, f4, p1, p2, c1, c2>>

SupCommit ==
    /\ sPC = "commit" /\ lock = 3
    /\ f1' = "superseded" /\ f2' = "active" /\ ptr' = 2
    /\ sPC' = "done" /\ lock' = 0
    /\ UNCHANGED <<f3, f4, p1, p2, c1, c2>>

Next ==
    \/ AddRead1 \/ AddCommit1
    \/ AddRead2 \/ AddCommit2
    \/ SupStart  \/ SupCommit

Spec == Init /\ [][Next]_vars

\* P1：新事实已 active 时，旧事实不许还是 active 且没有指针（半截 supersede）
AtomicSupersede ==
    ~(f2 = "active" /\ f1 = "active" /\ ptr = 0)

\* P2：任何一次已返回成功的 --add，其事实必须在最终文件里
NoLostUpdate ==
    /\ (c1 = "yes" => f3 = "active")
    /\ (c2 = "yes" => f4 = "active")

====
