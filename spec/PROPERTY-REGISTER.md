# 性质登记表 · para-memory 写入路径

> S0 建表、S5 收口。两条性质都是「坏了很贵、普通测试摸不到」：一条要两次落盘之间崩溃，
> 一条要两个写者同时读到同一版文件。模型在 `spec/`，反例回放在 `tests/test_write_path.py`。
> 一条命令重跑：`bash spec/run.sh`（0 守住 / 1 不符 / 2 工具链缺失）。

| 编号 | 性质（一句话，可被反例证伪） | owner | 覆盖的文件/函数 | 范围 | 证据等级 | 破坏变体 / 证据命令 | 退出码 | S4 日志 | 状态 | sync commit | 承诺变更证据 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 一次 `--supersede` 要么同时落盘「新事实存在 + 旧事实 `superseded` + `supersededBy` 指向新 id」，要么文件停在操作前；崩溃不得留下两条 `active` 且无指针 | Chief | `skills/para-memory/scripts/update_entity.py`（`supersede_fact`、`write_items_atomic`） | 单机 POSIX 文件系统；只覆盖 `--supersede` 路径；不覆盖「用户手工编辑 `items.json`」 | L2 | 破坏变体 `spec/ParaMemoryPartial.tla`（把一次落盘拆成两次 + 崩溃）；真实回放 `tests/test_write_path.py` 的 `TestSupersedeIsAtomic`；`bash spec/run.sh` | 0 | 无日志面：半截状态事后不可观测（文件不记录「谁取代谁」的意图），只能靠崩溃注入复现 ⟹ 未达 L3 | 守住（单机 POSIX，仅 --supersede） | 037079081dff13eb169d2ef233d65e7bf7e9eace |  |
| P2 | 同一实体的两个并发 `--add`，两条都必须留在最终 `items.json` 里，且 fact id 不重复 | Chief | `skills/para-memory/scripts/update_entity.py`（`add_fact`、`entity_lock`、`next_fact_id`） | 同一台机器上的多进程与多线程；POSIX `flock`；NFS 上的 `flock` 语义未验证；Windows 退化为「只有原子写、没有互斥」 | L2 | 破坏变体 `spec/ParaMemoryLostUpdate.tla`（去掉锁、写读到的快照）；真实回放 `tests/test_write_path.py` 的 `TestConcurrentAddLosesNothing`；`bash spec/run.sh` | 0 | 无日志面：丢失的写入不会留痕，只能靠并发注入复现 ⟹ 未达 L3 | 守住（同机多进程，POSIX flock） | 037079081dff13eb169d2ef233d65e7bf7e9eace |  |

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
