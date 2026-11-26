# ParaMemoryLostUpdate

TLC reached 14 states and 14 steps. The chart draws 14 states and 14 arrows.

## NoLostUpdate breaks
The shortest path has 4 steps:
0. v3_2="absent" v4_1="absent" c1="no" c2="no" p1="read" p2="read" f3="absent" f4="absent"
1. Read1: v3_2="absent" v4_1="absent" c1="no" c2="no" p1="write" p2="read" f3="absent" f4="absent"
2. Read2: v3_2="absent" v4_1="absent" c1="no" c2="no" p1="write" p2="write" f3="absent" f4="absent"
3. Commit1: v3_2="absent" v4_1="absent" c1="yes" c2="no" p1="done" p2="write" f3="active" f4="absent"
4. Commit2: v3_2="absent" v4_1="absent" c1="yes" c2="yes" p1="done" p2="done" f3="absent" f4="active"
