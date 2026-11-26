---- MODULE ParaMemoryPartial ----
\* 破坏变体 B：**supersede 分两次落盘**（先写新事实，再回头改旧事实）。
\* 两次之间崩溃 ⟹ 新事实 active、旧事实仍 active、指针为空。
\* 只建模 supersede，所以只会因 AtomicSupersede 报红。
EXTENDS Naturals

VARIABLES f1, f2, ptr, sPC
vars == <<f1, f2, ptr, sPC>>

Init ==
    /\ f1 = "active" /\ f2 = "absent" /\ ptr = 0 /\ sPC = "idle"

\* 第 1 次落盘
WriteNew ==
    /\ sPC = "idle"
    /\ f2' = "active" /\ sPC' = "mark"
    /\ UNCHANGED <<f1, ptr>>

\* 第 2 次落盘
MarkOld ==
    /\ sPC = "mark"
    /\ f1' = "superseded" /\ ptr' = 2 /\ sPC' = "done"
    /\ UNCHANGED <<f2>>

\* 两次之间进程死掉
Crash ==
    /\ sPC = "mark"
    /\ sPC' = "crashed"
    /\ UNCHANGED <<f1, f2, ptr>>

Next == WriteNew \/ MarkOld \/ Crash
Spec == Init /\ [][Next]_vars

AtomicSupersede ==
    ~(f2 = "active" /\ f1 = "active" /\ ptr = 0)

====
