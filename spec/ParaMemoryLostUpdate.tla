---- MODULE ParaMemoryLostUpdate ----
\* 破坏变体 A：**没有锁，读与写分成两次、写的是读到的快照**
\* （= 当前 update_entity.py 的语义：generate_fact_id 先读一次，add_fact 再读一次，最后整份覆盖）。
\* 只建模并发 --add，所以只会因 NoLostUpdate 报红。
EXTENDS Naturals

VARIABLES f3, f4, v4_1, v3_2, p1, p2, c1, c2
vars == <<f3, f4, v4_1, v3_2, p1, p2, c1, c2>>

Init ==
    /\ f3 = "absent" /\ f4 = "absent"
    /\ v4_1 = "absent" /\ v3_2 = "absent"
    /\ p1 = "read" /\ p2 = "read"
    /\ c1 = "no"  /\ c2 = "no"

\* 写者 1 读：把当时 f4 的样子拷进自己的快照
Read1 ==
    /\ p1 = "read"
    /\ v4_1' = f4 /\ p1' = "write"
    /\ UNCHANGED <<f3, f4, v3_2, p2, c1, c2>>

\* 写者 1 写：用**自己的快照**重建整份文件
Commit1 ==
    /\ p1 = "write"
    /\ f3' = "active" /\ f4' = v4_1
    /\ c1' = "yes" /\ p1' = "done"
    /\ UNCHANGED <<v4_1, v3_2, p2, c2>>

Read2 ==
    /\ p2 = "read"
    /\ v3_2' = f3 /\ p2' = "write"
    /\ UNCHANGED <<f3, f4, v4_1, p1, c1, c2>>

Commit2 ==
    /\ p2 = "write"
    /\ f4' = "active" /\ f3' = v3_2
    /\ c2' = "yes" /\ p2' = "done"
    /\ UNCHANGED <<v4_1, v3_2, p1, c1>>

Next == Read1 \/ Commit1 \/ Read2 \/ Commit2
Spec == Init /\ [][Next]_vars

NoLostUpdate ==
    /\ (c1 = "yes" => f3 = "active")
    /\ (c2 = "yes" => f4 = "active")

====
