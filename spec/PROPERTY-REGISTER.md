# 性质登记表 · para-memory 写入路径

> S0 建表、S5 收口。两条性质都是「坏了很贵、普通测试摸不到」：一条要两次落盘之间崩溃，
> 一条要两个写者同时读到同一版文件。模型在 `spec/`，反例回放在 `tests/test_write_path.py`。
> 一条命令重跑：`bash spec/run.sh`（0 守住 / 1 不符 / 2 工具链缺失）。

| 编号 | 性质（一句话，可被反例证伪） | owner | 覆盖的文件/函数 | 范围 | 证据等级 | 破坏变体 / 证据命令 | 退出码 | S4 日志 | 状态 | sync commit | 承诺变更证据 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 一次 `--supersede` 要么同时落盘「新事实存在 + 旧事实 `superseded` + `supersededBy` 指向新 id」，要么文件停在操作前；崩溃不得留下两条 `active` 且无指针 | Chief | `skills/para-memory/scripts/update_entity.py`（`supersede_fact`、`write_items_atomic`） | 单机 POSIX 文件系统；只覆盖 `--supersede` 路径；不覆盖「用户手工编辑 `items.json`」 | L2 | 破坏变体 `spec/ParaMemoryPartial.tla`（把一次落盘拆成两次 + 崩溃）；真实回放 `tests/test_write_path.py` 的 `TestSupersedeIsAtomic`；`bash spec/run.sh` | 0 | 无日志面：半截状态事后不可观测（文件不记录「谁取代谁」的意图），只能靠崩溃注入复现 ⟹ 未达 L3 | 守住（单机 POSIX，仅 --supersede） | 037079081dff13eb169d2ef233d65e7bf7e9eace |  |
| P2 | 同一实体的两个并发 `--add`，两条都必须留在最终 `items.json` 里，且 fact id 不重复 | Chief | `skills/para-memory/scripts/update_entity.py`（`add_fact`、`entity_lock`、`next_fact_id`） | 同一台机器上的多进程与多线程；POSIX `flock`；NFS 上的 `flock` 语义未验证；Windows 退化为「只有原子写、没有互斥」 | L2 | 破坏变体 `spec/ParaMemoryLostUpdate.tla`（去掉锁、写读到的快照）；真实回放 `tests/test_write_path.py` 的 `TestConcurrentAddLosesNothing`；`bash spec/run.sh` | 0 | 无日志面：丢失的写入不会留痕，只能靠并发注入复现 ⟹ 未达 L3 | 守住（同机多进程，POSIX flock） | 037079081dff13eb169d2ef233d65e7bf7e9eace |  |

## 为什么是两条而不是一条（可分离性实测）

P1 与 P2 都发生在写入路径上，很容易被当成「同一个失败家族」合并成一条更粗的性质。**不能合。**
判据不是「像不像同一类」，而是「**能不能用破坏变体把两条分开**」。

`spec/ParaMemorySeparability.tla` 把两种失败机制放进同一个模块，用 `FixAtomic` / `FixLock` 两个开关各自控制修法，
然后 4 种组合 × 2 条不变量逐个跑（`bash spec/run-separability.sh`，退出码 0/1/2）：

| FixAtomic | FixLock | AtomicSupersede | NoLostUpdate |
|---|---|---|---|
| TRUE | TRUE | 守住（rc 0） | 守住（rc 0） |
| TRUE | FALSE | 守住（rc 0） | **违反（rc 12）** |
| FALSE | TRUE | **违反（rc 12）** | 守住（rc 0） |
| FALSE | FALSE | 违反（rc 12） | 违反（rc 12） |

**关掉谁的修法，就只红谁的那一条** ⟹ 两个失败机制相互独立，合并会把「哪一处退化了」这个信息弄丢。

第一次跑这个实验时，`FALSE/TRUE` 那一格的 `NoLostUpdate` 报的是 **rc=11 死锁**而不是 rc=0：
破坏变体让崩溃把 `lock` 永久占住，并发那条路再也进不去。真实的 `flock` 随进程死亡由内核释放，
所以这是**模型的错**，不是代码的发现——改成崩溃时释放锁之后才得到上表。
教训：破坏变体也要建模「崩溃时资源被释放」，否则会造出一个看起来像发现的假信号。

## 空实现必须失败（已实测）

把 `supersede_fact` / `add_fact` 分别替换成 `return None` 后重跑：

- P1 → `操作没有真正生效（status=active）——空实现不许通过本测试`
- P2 → `'concurrent fact A' not found in ['Series A closed at $8M'] : 写入 A 丢了`

两条都按名字报红，复原后全绿。没有这一步，「测试通过」可能只是「什么都没做」。

## 这一轮发现的两个工具事实

- `statechart` 的解析器**不接受 `EXTENDS Naturals, TLC`**：只要 `EXTENDS` 里带 `TLC`，它就以
  `Cannot read properties of undefined (reading 'tag')` 退出 2；把 `, TLC` 去掉即恢复。
  最小复现：3 个标量变量 + 单个 action，仅改 `EXTENDS` 一行，前者 rc=2、后者 rc=0。
  模型里没有用到任何 TLC 专有算子，所以直接去掉。
- 同一个报错也会由**一个 action 里重复赋值同一个变量**（例如既写 `x'` 又把它列进 `UNCHANGED <<...>>`）触发。
  两种成因的报错文本完全一样，只能靠二分定位。

## 没做的事（写清楚，不留「大概没问题」）

- **S4 没有日志面**：这两条性质都不是「跑完能对日志」的类型，落成 L2。
- **`--check` 之类的运行期断言没加**：半截 supersede 事后无法与「两条合法的 active 事实」区分，
  加一个只查「指针是否悬空」的断言会给人「已守住」的错觉，所以不加。
- **链完整性（`supersededBy` 是否指向存在的 active 事实）未建模**：它是另一条性质，
  要建模得回 S1 重来，这一轮不做。

## S1 出口未补齐（2026-11-27 复查，不偷偷修，先记账）

以下三项是 `references/stations.md` 的 S1 出口判据，本轮**没做到**，所以 S1 只能算「模型已跑、未确认」，不能算完成：

1. **图确认记录缺失**——`stations.md:35` 要求「确认人 / 日期 / 那一版图」写进验证记录的 A 分区，缺这一行等于没做过「先画图让人确认」。本轮只有 `spec/out-*/chart.mmd`，没有确认人。
2. **bounds 没写清**——S1 出口第 ③ 条要求「常数取多大、为什么够、`CONSTRAINT` 卡在哪」。本轮只靠有限状态空间，没有写常数与界。
3. **终态用关检查代替了 Done 动作**——`toolchain.md` 硬约束 #3 要求加 `Done == pc \in {...} /\ UNCHANGED vars`；本轮改用 `CHECK_DEADLOCK FALSE` 把死锁检查整个关掉。`toolchain.md` 同时写着「`-deadlock` 的语义是『不要』检查死锁」，这条读反了。

补齐代价：每份模型加 3 行 `Done`，重跑一次 `bash spec/run.sh`，再把状态数连同 `-workers` 一起记。未做，因为本轮的任务是审计这次运行本身。

## 范围边界：这张表只覆盖 `items.json` 的写入路径

上面两条性质的覆盖范围是 `update_entity.py` 的 `--supersede` 与并发 `--add`，都落在
`items.json` 这一份文件上。**捕获、查询、合成三条链路不在本表范围内**，它们失效时不会留下
「半截状态」这种东西，看到的就是错的结果本身，所以按普通测试守（证据等级 L1），不按不变量守（L2）。
不把 L1 的绿写进本表，是为了不让「有登记表」被读成「这些路径都被模型检查过」。

2026-11-27 第二轮修复（C1/C4/C5/C6/C7/C8 + hook 解释器）的守门测试：

| 缺陷 | 症状（实测） | 守门测试 | 破坏变体（必须红） |
|---|---|---|---|
| C1 捕获只存第一轮 | 二次触发后文件仍 16 行、新消息 grep=0，日志却写 Updated | `tests/test_capture_path.py::test_second_capture_drops_nothing_from_the_first` | 退回「只改时间戳」 |
| C2 3.9 上 import 就崩 | `python3.9 save_chat_history.py` → `TypeError: unsupported operand type(s) for \|` | `…::test_hook_runs_under_the_oldest_python_available`（本机 `/usr/bin/python3` = 3.9.6） | 去掉 `from __future__ import annotations` |
| C3 注册命令是裸 `python` | 本机无 `python`，hook 静默不执行 | `tests/test_install_hooks.py::test_registered_command_actually_captures_a_session` | 退回 `python <script>` |
| C4 embed 不限集合 / 被 600 s 掐死 | `qmd embed` 不带 `-c` 会向量化用户全部集合；2 s/chunk 下 600 s 只够 ~301 chunk | `tests/test_synthesis.py::test_every_embed_call_is_scoped_to_one_collection`、`…::test_embed_carries_no_wall_clock_cap_by_default` | 去掉 `-c` / 去掉 `--timeout 0` |
| C5 索引失败仍报完成 | 去掉 qmd 的 PATH → rc=0 且打印 `✓ Synthesis complete!` | `…::test_failed_index_refresh_exits_nonzero`、`…::test_failed_embedding_exits_nonzero`、`…::test_missing_qmd_points_at_the_upstream_package` | 退回 `return 0` |
| C7 summary.md 非原子 | `write_text` 覆写，写一半崩即半截文件 | `…::test_crash_during_summary_write_keeps_the_previous_version` | 退回 `write_text` |
| C8 date 模式断链 | `search_timeline.sh date 2026-11-27` → rc=1（捕获写的是 `<date>-<id>-session.md`） | `tests/test_query_scripts.py::test_date_mode_reads_capture_files_for_that_day` | 退回 `files=("$DIR/$DATE.md")` |

一条命令重跑全部破坏变体：`python3 tests/destruct_variants.py`（21/21 各自按名字红；跑在
`git worktree` 临时副本里，不碰工作区）。它的意义是：
全绿本身不证明这些测试有分辨力，必须看到每处修法退回旧写法时**对应的**那条测试报红。

qmd CLI 的三条实测约束（`-c` 对 `update` 无效、`embed` 只认第一个 `-c`、`--timeout` 到点截断却
仍 rc=0）记在 `skills/para-memory/references/qmd_setup.md` 的「During weekly synthesis」。

## 第二轮：GLM-5.3 复审后的补修（同一批路径）

复审在 33 条测试全绿、18 条破坏变体自证的前提下又找出 1 条 P1 与若干 P2。它们都不是
「测试写错了」，而是「修法只覆盖了我想到的那条路」。记在这里，避免下一轮把同样的话再说一遍。

| 缺陷 | 症状（实测） | 守门测试 | 破坏变体 |
|---|---|---|---|
| P1 会话归属按文件名前缀 | `ab-12345…` 与 `ab.12345…` 净化后同前缀；后到的会话把先到的整份文件重渲染掉，无告警 | `test_capture_path.py::test_two_sessions_sharing_a_filename_prefix_keep_separate_files` | 退回按文件名认领 |
| P2 txt 分支自成规则 | `.txt` 自己拼日期，跨天又开一个文件，与 JSONL 路径不一致 | `…::test_txt_capture_follows_the_same_file_rule` | 退回自己拼日期 |
| P2 原子写改权限 | `mkstemp` 0600 → rename 后 `settings.json` 0644 变 0600 | `test_atomic_io.py::test_an_existing_file_keeps_its_mode` | 去掉 chmod |
| P2 坏 items.json 炸全轮 | 一个半写 JSON 让其后实体全无 summary，报裸 traceback | `test_synthesis.py::test_one_broken_items_json_does_not_stop_the_other_entities` | except 换成 `ZeroDivisionError` |
| P2 旧 summary 复活 | 无 `## Hot Facts` 的旧文件被整份当 overview 保留，陈旧内容每轮回来 | `…::test_a_summary_without_markers_is_rebuilt_not_carried_over` | 退回 `split("## Hot Facts")` |
| P2 keyword 把坏 store 报成零命中 | store 被移走 → `No matches found`、rc=0 | `test_query_scripts.py::test_keyword_against_a_missing_store_is_not_reported_as_no_match` | 去掉 `require_store` |
| P2 短日期/元字符 | `date 2026-11-2` 漏到 20 号；`date '*'` 匹配全部 | `…::test_date_mode_rejects_a_partial_date`、`…::test_date_mode_rejects_glob_metacharacters` | 去掉格式校验 |
| P2 跳过与完成同为 rc=0 | 调用方靠 stdout 猜索引状态 | `test_synthesis.py::test_index_status_is_machine_readable`（`index=updated/skipped/failed` 走 stderr） | — |
| P2 临时解释器静默失效 | venv 删掉后 hook 停摆 | `test_install_hooks.py::test_a_throwaway_interpreter_is_flagged` | — |
| P3 变体脚本有 kill 窗口 | 原地打补丁被 kill -9 → 仓库留在被破坏状态 | 变体改跑 `git worktree` 临时副本 | — |
| P3 bash 3.2 吞字节 | `$DATE（` → stderr 少一个字节，Python 侧 UnicodeDecodeError | `test_shell_hygiene.py::test_variables_are_braced_before_multibyte_text` | 退回 `$DATE（` |

两条与平台有关、写进代码注释的实测事实：

- **BSD grep（macOS）对不存在的目录返回 1**，和「零命中」一样；GNU grep 才返回 2。所以
  `search_timeline.sh` 的 `require_store` 是主守卫，`case "$rc"` 只是 Linux 侧的保险。
- **bash 3.2 的 `$VAR` 紧贴多字节字符会吞字节**，且不报错 —— 只能靠 `${VAR}` 与机器扫描。

## 第三轮：一条 P1 回归 + 三处 P2/P3（同一条路径，GLM-5.3 增量复审）

第二轮把「按头部认领」只用在了有 id 的分支上，无 id 的分支仍然是 `candidates[0]`；而候选集
新增的 `*-<short>-*-session.md` 会把「带 digest 后缀、头部写着别人 id」的文件也捞进来。于是
一个 `.txt` 捕获能把另一个会话的文件整份覆盖 —— 上一轮 P1 的同款，换了一条路径复发。

| 缺陷 | 症状（实测） | 守门测试 | 破坏变体 |
|---|---|---|---|
| P1 txt 覆盖有主文件 | 预置 `…-ab-12345-d41d-session.md`（头部 `ab-12345-xyz-987`），跑 `ab.12345.txt` 后该文件变成 raw txt，会话 A 消失 | `test_capture_path.py::test_txt_capture_never_overwrites_a_file_that_belongs_to_a_session` | 退回 `return candidates[0]` |
| P2 overview 切进代码围栏 | Overview 里 ```md 围栏含 `## ` 行时，围栏后半与 `## My Notes` 整节被静默丢弃 | `test_synthesis.py::test_a_code_fence_inside_the_overview_survives` | 退回正则截到第一个 `## ` |
| P2 弱证据 | C6 与 keyword 两条变体的 `expect` 取自「旧行为输出里恰好出现的串」，相邻原因也可能命中 | 两条断言补自定义消息，`expect` 改取消息本身 | — |
| P3 身份行读取窗口 | `read_head` 按字节截 4096，超长 slug 会把 `**Session:**` 挤出窗口，会话被当成新的 | `…::test_a_very_long_slug_does_not_hide_the_identity_line` | 退回 `handle.read(4096)` |
| P3 升级后同会话裂两份 | 有 id 的会话不认领无头旧文件，旧文件留成陈旧副本（不丢数据，docstring 已声明取舍） | 未修，记录在案 | — |

**这一轮学到的**：扩大一个候选集（多一个 glob）时，要把**所有**消费它的分支都重读一遍。
有 id 的分支加了头部闸门，无 id 的分支没有 —— 修好一条路径，顺手给另一条路径递了更宽的输入。
