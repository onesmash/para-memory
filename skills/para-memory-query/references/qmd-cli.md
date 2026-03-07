# QMD CLI Reference

Quick reference for using `qmd` CLI to search PARA memory collections.

> Full docs: https://github.com/tobi/qmd

## Status Check

```bash
qmd status
```

## Query Commands

### Basic query (auto-expand + rerank)

```bash
qmd query "your question here"
```

### Structured query (combine types for better recall)

```bash
qmd query $'lex: exact keywords\nvec: natural language question'
```

### Keyword-only search (BM25, no LLM)

```bash
qmd search "keywords"
```

### Get a document by ID or path

```bash
qmd get "#abc123"
qmd get "path/to/file.md"
```

### Batch retrieve by glob or list

```bash
qmd multi-get "memory/2026-*.md" -l 40
qmd multi-get notes/foo.md,notes/bar.md
```

## Query Types

| Type | Method | Best for |
|------|--------|----------|
| `lex` | BM25 keyword | Exact terms, names, code identifiers |
| `vec` | Vector semantic | Natural language questions |
| `hyde` | Hypothetical doc | Complex topics, write what the answer looks like |
| `expand` | Auto-expand | Single-line query, lets LLM generate variants |

### Combining types (best recall)

```bash
# lex + vec
qmd query $'lex: authentication JWT\nvec: how does user login work'

# lex + vec + hyde
qmd query $'lex: pricing strategy\nvec: discussion about product pricing\nhyde: We decided to use a tiered pricing model based on usage, with a free tier for small teams and paid plans starting at $X per seat'
```

First query type gets 2x weight in fusion — put your best guess first.

## Collection Filtering

Filter to a specific PARA memory layer:

```bash
# Single collection
qmd query "query" -c knowledge
qmd query "query" -c daily
qmd query "query" -c tacit

# All collections (default)
qmd query "query"
```

## Lex Query Syntax

| Syntax | Meaning | Example |
|--------|---------|---------|
| `term` | Prefix match | `auth` matches "authentication" |
| `"phrase"` | Exact phrase | `"rate limiter"` |
| `-term` | Exclude | `meeting -standup` |

Note: `-term` exclusion only works in `lex` queries.

## Tips for PARA Memory Searches

- **Unsure what to search**: Use a single natural language query — qmd auto-expands it
- **Looking for a person**: `qmd query "John Doe" -c knowledge`
- **Recent events**: `qmd query "last week project updates" -c daily`
- **Preferences/habits**: `qmd query "how I prefer to work" -c tacit`
- **Best recall on important queries**: combine `lex` (key terms) + `vec` (full question)
