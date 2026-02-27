# QMD Setup Guide

QMD (https://github.com/onesmash/qmd) provides semantic search capabilities for the memory system.

## Installation

Install QMD globally using Bun:

```bash
bun install -g github:onesmash/qmd
```

Ensure `~/.bun/bin` is in your PATH.

For macOS, install Homebrew SQLite for extension support:
```bash
brew install sqlite
```

## Initial Configuration

Configure API access for embeddings and semantic features:

```bash
qmd init
```

This creates `~/.config/qmd/api.yml`. Add your SiliconFlow API credentials to enable embeddings, query expansion, and reranking.

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
- Ensure `~/.bun/bin` is in PATH
- Reinstall: `bun install -g github:onesmash/qmd`

**Poor semantic search results**
- Check API configuration: `~/.config/qmd/api.yml`
- Rebuild embeddings: `qmd embed -f`

**Out of date results**
- Update index: `qmd update`
- Check collection paths: `qmd collection list`

**Slow searches**
- Reduce result count: `-n 5`
- Use keyword search for exact matches
- Check database size: `qmd ls <collection>`
