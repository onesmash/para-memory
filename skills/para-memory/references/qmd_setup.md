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
Update index and rebuild embeddings:

```bash
qmd update
qmd embed
```

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
qmd embed 
```

**Weekly synthesis:**
```bash
qmd update  # Update index
qmd embed   # Rebuild embeddings
```

**When search quality degrades:**
```bash
qmd embed -f  # Force full re-embedding
```

## Troubleshooting

**Command not found**
- 确认 npm 全局 bin 在 PATH 里（`npm prefix -g` 下的 `bin`）
- 确认 Node >= 22.6：`node --version`
- 重装：`npm install -g github:onesmash/qmd#cloud-api-2.9`

**Poor semantic search results**
- Check model configuration: `~/.config/qmd/index.yml` 的 `models:` 段；
  凭据是否就位看环境变量（`echo ${SILICONFLOW_API_KEY:+set}`）
- Rebuild embeddings: `qmd embed -f`

**Out of date results**
- Update index: `qmd update`
- Check collection paths: `qmd collection list`

**Slow searches**
- Reduce result count: `-n 5`
- Use keyword search for exact matches
- Check database size: `qmd ls <collection>`
