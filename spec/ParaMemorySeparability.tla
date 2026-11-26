---- MODULE ParaMemorySeparability ----
\* 可分离性实验：把两种失败机制放进**同一个模块**，用两个常量开关各自的修法，
\* 然后看每个破坏配置到底弄红了哪一条不变量。
\*
\*   FixAtomic = 一次落盘（P1 的修法）      FixLock = 每实体一把锁（P2 的修法）
\*
\* 目的：如果「关掉 A 的修法」只弄红 A、「关掉 B 的修法」只弄红 B，
\* 那么 P1 与 P2 是两个不同的失败，**不能**按「同一失败家族」合并成一条。
EXTENDS Naturals

CONSTANTS FixAtomic, FixLock

VARIABLES f1, f2, ptr, f3, f4, p1, p2, c1, c2, lock, sPC, v4_1, v3_2
vars == <<f1, f2, ptr, f3, f4, p1, p2, c1, c2, lock, sPC, v4_1, v3_2>>

Init ==
    /\ f1 = "active"  /\ f2 = "absent" /\ ptr = 0
    /\ f3 = "absent"  /\ f4 = "absent"
    /\ p1 = "read"    /\ p2 = "read"
    /\ c1 = "no"      /\ c2 = "no"
    /\ lock = 0       /\ sPC = "idle"
    /\ v4_1 = "absent" /\ v3_2 = "absent"

\* ============ P1 路径：supersede ============

SupStart ==
    /\ sPC = "idle" /\ lock = 0
    /\ lock' = 3 /\ sPC' = "commit"
    /\ UNCHANGED <<f1, f2, ptr, f3, f4, p1, p2, c1, c2, v4_1, v3_2>>

\* 修法在：两处改动一次落盘
SupCommitAtomic ==
    /\ FixAtomic
    /\ sPC = "commit" /\ lock = 3
    /\ f1' = "superseded" /\ f2' = "active" /\ ptr' = 2
    /\ sPC' = "done" /\ lock' = 0
    /\ UNCHANGED <<f3, f4, p1, p2, c1, c2, v4_1, v3_2>>

\* 修法不在：先写新事实，再回头改旧事实（两步）
SupWriteNew ==
    /\ ~FixAtomic
    /\ sPC = "commit" /\ lock = 3
    /\ f2' = "active" /\ sPC' = "mark"
    /\ UNCHANGED <<f1, ptr, f3, f4, p1, p2, c1, c2, lock, v4_1, v3_2>>

SupMarkOld ==
    /\ ~FixAtomic
    /\ sPC = "mark"
    /\ f1' = "superseded" /\ ptr' = 2 /\ sPC' = "done" /\ lock' = 0
    /\ UNCHANGED <<f2, f3, f4, p1, p2, c1, c2, v4_1, v3_2>>

\* 两次之间进程死掉
SupCrash ==
    /\ ~FixAtomic
    /\ sPC = "mark"
    /\ sPC' = "crashed"
    /\ lock' = 0          \* 进程死掉时 flock 由内核释放，不会把锁带走
    /\ UNCHANGED <<f1, f2, ptr, f3, f4, p1, p2, c1, c2, v4_1, v3_2>>

\* ============ P2 路径：并发 --add ============

\* 修法在：取锁 → 直接改目标条目 → 放锁
AddRead1Locked ==
    /\ FixLock
    /\ p1 = "read" /\ lock = 0
    /\ lock' = 1 /\ p1' = "write"
    /\ UNCHANGED <<f1, f2, ptr, f3, f4, p2, c1, c2, sPC, v4_1, v3_2>>

AddCommit1Locked ==
    /\ FixLock
    /\ p1 = "write" /\ lock = 1
    /\ f3' = "active" /\ c1' = "yes" /\ lock' = 0 /\ p1' = "done"
    /\ UNCHANGED <<f1, f2, ptr, f4, p2, c2, sPC, v4_1, v3_2>>

AddRead2Locked ==
    /\ FixLock
    /\ p2 = "read" /\ lock = 0
    /\ lock' = 2 /\ p2' = "write"
    /\ UNCHANGED <<f1, f2, ptr, f3, f4, p1, c1, c2, sPC, v4_1, v3_2>>

AddCommit2Locked ==
    /\ FixLock
    /\ p2 = "write" /\ lock = 2
    /\ f4' = "active" /\ c2' = "yes" /\ lock' = 0 /\ p2' = "done"
    /\ UNCHANGED <<f1, f2, ptr, f3, p1, c1, sPC, v4_1, v3_2>>

\* 修法不在：读快照 → 用快照整份覆盖
AddRead1Snapshot ==
    /\ ~FixLock
    /\ p1 = "read"
    /\ v4_1' = f4 /\ p1' = "write"
    /\ UNCHANGED <<f1, f2, ptr, f3, f4, p2, c1, c2, lock, sPC, v3_2>>

AddCommit1Snapshot ==
    /\ ~FixLock
    /\ p1 = "write"
    /\ f3' = "active" /\ f4' = v4_1
    /\ c1' = "yes" /\ p1' = "done"
    /\ UNCHANGED <<f1, f2, ptr, p2, c2, lock, sPC, v4_1, v3_2>>

AddRead2Snapshot ==
    /\ ~FixLock
    /\ p2 = "read"
    /\ v3_2' = f3 /\ p2' = "write"
    /\ UNCHANGED <<f1, f2, ptr, f3, f4, p1, c1, c2, lock, sPC, v4_1>>

AddCommit2Snapshot ==
    /\ ~FixLock
    /\ p2 = "write"
    /\ f4' = "active" /\ f3' = v3_2
    /\ c2' = "yes" /\ p2' = "done"
    /\ UNCHANGED <<f1, f2, ptr, p1, c1, lock, sPC, v4_1, v3_2>>

\* 终态自环：按 stations.md S1 第 4 条的做法，而不是关掉死锁检查
Done ==
    /\ p1 = "done" /\ p2 = "done" /\ sPC \in {"done", "crashed"}
    /\ UNCHANGED vars

Next ==
    \/ Done
    \/ SupStart
    \/ SupCommitAtomic \/ SupWriteNew \/ SupMarkOld \/ SupCrash
    \/ AddRead1Locked \/ AddCommit1Locked \/ AddRead2Locked \/ AddCommit2Locked
    \/ AddRead1Snapshot \/ AddCommit1Snapshot \/ AddRead2Snapshot \/ AddCommit2Snapshot

Spec == Init /\ [][Next]_vars

AtomicSupersede ==
    ~(f2 = "active" /\ f1 = "active" /\ ptr = 0)

NoLostUpdate ==
    /\ (c1 = "yes" => f3 = "active")
    /\ (c2 = "yes" => f4 = "active")

====
