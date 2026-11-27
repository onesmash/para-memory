# QMD Setup Guide

QMD (https://github.com/tobi/qmd) provides semantic search capabilities for the memory system.
**只用上游版本**：不再维护 fork，也没有任何云端 API 依赖。

## Installation

上游 2.9.0 本身就是官方 Node 实现（`better-sqlite3` 自带 FTS5），**不需要 bun、没有构建步骤**：

```bash
# 需要 Node >= 22
npm install -g @tobilu/qmd@2.9.0
```

装完 `qmd --version` 应输出 `qmd 2.9.0 (<commit>)`；npm 的全局 bin 目录要在 `PATH` 里。

说明两点：

- **没有 API key**。embed / rerank / query-expansion 三条都是本地 GGUF，首次用到时自动下到
  `~/.cache/qmd/models/`（合计约 **2.13 GB**）：`embeddinggemma-300M-Q8_0.gguf` 318 MB、
  `qwen3-reranker-0.6b-q8_0.gguf` 610 MB、`qmd-query-expansion-1.7B-q4_k_m.gguf` 1.2 GB。
- **下载慢就加镜像**：`HF_ENDPOINT=https://hf-mirror.com qmd embed`。

## Initial Configuration

`~/.config/qmd/index.yml` 只写 collections，**不要写 `models:` 段**——留空即用内置默认模型。
（上游不读 `api.yml`；本机此前那份 SiliconFlow 配置已移出配置目录。）

## 本机实测（Intel Mac，无 GPU，2026-11-27）

```
qmd embed -c code    100 chunks / 33 docs → 3m19s（≈2 s/chunk）
qmd vsearch ...      正常出结果
qmd query ...        单次 ≈1m8s（含模型加载）
```

`qmd` 会提示 `no GPU acceleration, running on CPU (slow)`，属正常。**按 2 s/chunk 估算**：
五千个文件（约 1.6 万 chunk）全量重建约 **8–9 小时**，建议一次跑完。

换 embedding 模型会让已有向量失效（向量空间由「模型+维度+revision」共同决定），必须
`qmd embed -f` 重建；`qmd status` 会显示还有多少待嵌入。

## Setting Up Collections

Collections map to the three memory layers:

```bash
# Knowledge graph (PARA structure)
qmd collection add base_path/knowledge --name knowledge

# Daily notes (timeline)
qmd collection add base_path/memory --name daily

# List collections
qmd collection list
```

## Adding Context

Add descriptive metadata to help search understand your content:

```bash
qmd context add qmd://knowledge "PARA-organized entities: people, companies, projects with atomic facts"
qmd context add qmd://daily "Daily conversation timeline and event log"
qmd context add qmd://tacit "Long term memory"
```

## Indexing

Generate vector embeddings for semantic search:

```bash
# Initial embedding
qmd embed

# Force re-embed everything
qmd embed -f
```

Update the index when documents change:

```bash
# Update index
qmd update

# Update with git pull first
qmd update --pull
```

## Search Modes

QMD provides three search modes:

### Keyword Search
Fast BM25 full-text search. Good for finding specific facts.

```bash
# Search across all collections
qmd search "Jane's role at Acme"

# Search in specific collection
qmd search "Jane's role" -c knowledge

# Get more results
qmd search "pricing" -n 10
```

### Semantic Search
Vector similarity search. Good for finding related information.

```bash
# Semantic search
qmd vsearch "career changes and promotions"

# In specific collection
qmd vsearch "project timeline discussions" -c daily
```

### Hybrid Search (Recommended)
Combines keyword and semantic search with query expansion and reranking.

```bash
# Best for most queries
qmd query "when did the project scope change"

# Specify collection
qmd query "Jane's preferences" -c knowledge

# More results
qmd query "meetings about product" -n 15
```

## Common Options

- `-n <num>` - Number of results (default: 5)
- `-c, --collection` - Restrict to specific collection
- `--all` - Return all matches
- `--json` - JSON output for scripting
- `--files` - List format with scores
- `--min-score <num>` - Filter by relevance threshold

## Retrieving Documents

Get specific documents:

```bash
# By path
qmd get "areas/people/john-doe/summary.md"

# By document ID
qmd get "#abc123"

# Using glob patterns
qmd multi-get "areas/people/*/summary.md"
```

## Search Tips

1. **Use hybrid search by default** - `qmd query` combines best of both worlds

2. **Specify collections** when you know where to look
   - `-c knowledge` for entity facts
   - `-c daily` for timeline events

3. **Adjust result count** based on need
   - Default 5 results for quick lookups
   - Increase with `-n 20` for broader exploration

4. **Use appropriate search mode**
   - Exact phrases → keyword search
   - Concepts and meaning → semantic search
   - General queries → hybrid search

## Integration with Memory System

### After fact extraction
Update index when new facts are added:

```bash
qmd update
```

### During weekly synthesis

`weekly_synthesis.py` 自己会做，不需要手敲。它做的事和为什么这样做：

```bash
qmd update                                  # ① 刷新文件索引
qmd embed -c knowledge --timeout 0           # ② 每个记忆集合各一次
qmd embed -c daily     --timeout 0
```

三条实测约束（2026-11-27，qmd 2.9.0）：

1. **`qmd update` 没有集合过滤。** `qmd update -c x` 会静默忽略 `-c` 并刷新全部集合，所以这一步
   只能全局跑。它是文件索引的哈希扫描（不是向量化），代价可控；真正贵的那一半在 ②。
2. **`qmd embed` 只认第一个 `-c`，并且会校验集合名**（不存在时 `Collection not found: X`，rc=1）。
   所以按集合逐个调用，别想一次 `-c a -c b`。
3. **`qmd embed --timeout` 到点是「截断但成功」**：实测 `--timeout 0.05` 在 13 秒时停下，仍打印
   `✓ Done! Embedded 12 chunks` 且 rc=0。所以脚本默认传 `--timeout 0`（不限时），把退出码当唯一
   信号；如果你自己设了上限，请知道它可能只嵌了一半而 rc 仍是 0。

索引没更新成功时，`weekly_synthesis.py` 退出码非 0 并打印 `索引未更新`（可用 `--skip-qmd` 显式跳过）。
集合名不一样的话用 `QMD_COLLECTIONS="a b"` 覆盖，qmd 可执行文件不在 PATH 上时用 `QMD_BIN=/path/to/qmd`。

### During conversation
Search before loading into context:

```bash
# Find relevant entities
qmd query "customer feedback" -c knowledge

# Then load only relevant summary.md files
```

## Maintenance

**After adding/updating entities:**
```bash
qmd update
qmd embed -c knowledge    # 一次一个集合，见上面「During weekly synthesis」
```

**Weekly synthesis:**
```bash
python3 skills/para-memory/scripts/weekly_synthesis.py   # 自己会 update + 逐集合 embed
```

**When search quality degrades:**
```bash
qmd embed -f  # Force full re-embedding
```

## Troubleshooting

**Command not found**
- 确认 npm 全局 bin 在 PATH 里（`npm prefix -g` 下的 `bin`）
- 确认 Node >= 22：`node --version`
- 重装：`npm install -g @tobilu/qmd@2.9.0`

**Poor semantic search results**
- `~/.config/qmd/index.yml` 里**不该有** `models:` 段；有的话删掉，走内置默认模型
- 向量是不是用别的模型生成的：`qmd status` 看 Pending / Vectors，换过模型就 `qmd embed -f`
- 首次跑要注意模型是否下完（`ls ~/.cache/qmd/models/`，三个 gguf 共约 2.13 GB）

**Out of date results**
- Update index: `qmd update`
- Check collection paths: `qmd collection list`

**Slow searches**
- Reduce result count: `-n 5`
- Use keyword search for exact matches
- Check database size: `qmd ls <collection>`
