# QMD Setup Guide

QMD (https://github.com/onesmash/qmd) provides semantic search capabilities for the memory system.

## Installation

QMD 跑在**官方 Node** 上（不再需要 bun）：源码直接由 Node 做类型剥离执行，没有构建步骤。

```bash
# 需要 Node >= 22.6（推荐 24 LTS）
npm install -g github:onesmash/qmd#cloud-api-2.9
```

装完 `qmd --help` 能出用法即可；npm 的全局 bin 目录要在 `PATH` 里。

说明三点：

- **分支**：`main` 现在就是上游 `tobi/qmd`（2.9.0，本身就是官方 Node + `better-sqlite3`）。
  我们这侧只多了**云 API** 那一条线，放在 `cloud-api-2.9` 分支上：远程 embedding 上游
  已有（`http(s)://base#model`），我们补的是**通用的远程 rerank**（`/rerank`），
  因为上游原来只认 TypeSafe 一家。
- **SQLite**：数据库走 `better-sqlite3`（自带 FTS5，且允许加载扩展），
  **不再需要 Homebrew SQLite** 那一步。
- 旧的 `node-runtime` 分支已作废（它做的是 Bun→Node 迁移，上游自己已经做完了）。

## Initial Configuration

模型写在全局配置 `~/.config/qmd/index.yml` 的 `models:` 段里。远程端点用
`http(s)://API-base#模型ID` 的写法，**凭据只写环境变量名，不写值**：

```yaml
models:
  embed: https://api.siliconflow.cn/v1#Qwen/Qwen3-Embedding-0.6B
  embedOptions:
    dimensions: 1024          # 必须与模型输出维度一致
    apiKeyEnv: SILICONFLOW_API_KEY
  rerank: https://api.siliconflow.cn/v1#Qwen/Qwen3-Reranker-0.6B
  rerankOptions:
    apiKeyEnv: SILICONFLOW_API_KEY
  # 本地 query-expansion 模型（远程 generate 目前不支持，留默认或填本地 GGUF）
  generate: hf:tobil/qmd-query-expansion-1.7B-gguf/qmd-query-expansion-1.7B-q4_k_m.gguf
```

然后把 key 放进环境（不要写进配置文件）：

```bash
export SILICONFLOW_API_KEY=...     # 放进 shell profile，或由密钥管理注入
```

换 embedding 模型会让已有向量失效（向量空间由「端点+模型+维度+revision」共同决定），
旧索引需要重跑一次 `qmd embed`。`qmd status` 会显示还有多少待嵌入。

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
