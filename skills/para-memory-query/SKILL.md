---
name: para-memory-query
description: Query and retrieve information from a PARA-structured memory system with three layers (Knowledge Graph, Daily Notes, Tacit Knowledge). Use when the user asks about past information, people, projects, companies, preferences, or events. Triggers include "What do I know about...", "Find information about...", "What happened on...", "How do I prefer...", "What's the status of...", "List all my...", or any query about stored memories, entities, or past conversations.
---

# PARA Memory Query

Query a three-layer memory system organized using the PARA method (Projects, Areas, Resources, Archives).

## Overview

This skill enables querying a structured memory system with three distinct layers:

1. **Knowledge Graph** - Entities (people, projects, companies) organized in PARA directories with summary.md and items.json files
2. **Daily Notes** - Chronological timeline of events in dated markdown files (YYYY-MM-DD.md)
3. **Tacit Knowledge** - User patterns, preferences, and working style

### Environment Configuration (Optional)

Set the `PARA_MEMORY_ROOT` environment variable to customize the root directory:

```bash
# Set in your shell profile (~/.bashrc, ~/.zshrc, etc.)
export PARA_MEMORY_ROOT=~/para-memory

# Or use a custom location
export PARA_MEMORY_ROOT=/path/to/my/memory
```

**Default:** If not set, defaults to `~/para-memory/`

## Query Decision Tree

```
Is this about...
├─ A specific entity (person/project/company)?
│  └─ → Entity Lookup (read summary.md, query items.json)
│
├─ A specific date or time period?
│  └─ → Timeline Search (daily notes)
│
├─ User preferences or working style?
│  └─ → Tacit Knowledge Search (preferences.md)
│
└─ Unsure or complex query?
   └─ → Use QMD for semantic search across all layers
```

## Entity Lookups

For queries about people, projects, or companies:

1. **Check if entity exists** in PARA structure:
   - People: `${PARA_MEMORY_ROOT:-~/para-memory}/knowledge/areas/people/<name>/`
   - Projects: `${PARA_MEMORY_ROOT:-~/para-memory}/knowledge/projects/<name>/`
   - Companies: `${PARA_MEMORY_ROOT:-~/para-memory}/knowledge/areas/companies/<name>/`
   - Resources: `${PARA_MEMORY_ROOT:-~/para-memory}/knowledge/resources/<topic>/`

2. **Read summary.md first** for quick overview (always start here)

3. **Query items.json for details** using the query_entity.sh script:
   ```bash
   scripts/query_entity.sh areas/people/john-doe
   ```

4. **Filter by category** if needed:
   ```bash
   scripts/query_entity.sh projects/website '.[] | select(.category == "status")'
   ```

**Fact categories**: `relationship`, `milestone`, `status`, `preference`, `context`

## Timeline Queries

For queries about what happened when:

**Specific date**:
```bash
scripts/search_timeline.sh date 2026-01-15
```

**Date range**:
```bash
scripts/search_timeline.sh range 2026-02-01 2026-02-10
```

**Keyword search**:
```bash
scripts/search_timeline.sh keyword "authentication feature"
```

## Semantic Search with QMD

For complex or semantic queries where exact wording is unknown:

**Search all collections**:
```bash
scripts/search_qmd.sh "pricing strategy discussion"
```

**Search specific layer**:
- Knowledge graph: `scripts/search_qmd.sh "John's role" knowledge`
- Daily notes: `scripts/search_qmd.sh "started project" memory`
- Tacit knowledge: `scripts/search_qmd.sh "coding preferences" tacit`

**Note**: QMD must be installed and collections configured. Falls back to Grep/Glob if unavailable.

## Built-in Tool Alternatives

When QMD is unavailable or for simple queries:

**Find entities by pattern** (Glob):
```
pattern: **/people/*/summary.md
```

**Search content** (Grep):
```
pattern: "john|Jane"
path: ~/para-memory/knowledge/
```

**Query JSON facts** (via query_entity.sh with jq):
```bash
# All active facts
scripts/query_entity.sh areas/people/john '.[] | select(.status == "active")'

# Recent milestones
scripts/query_entity.sh projects/website '.[] | select(.category == "milestone")'

# Related entities
scripts/query_entity.sh areas/companies/acme '.[] | select(.relatedEntities | length > 0)'
```

## Tiered Retrieval Strategy

Always follow this order to minimize context usage:

1. **summary.md** - Quick overview (load first)
2. **items.json** - Detailed facts (only if summary insufficient)
3. **Daily notes** - Full timeline (only for historical context)

Facts are organized by recency:
- **Hot** (last 7 days): In summary, most relevant
- **Warm** (8-30 days): In summary, lower priority
- **Cold** (30+ days): In items.json only, searchable but not in summary

## Common Query Patterns

For detailed examples and strategies, see [query-patterns.md](references/query-patterns.md).

**Quick examples**:

- "What do I know about John?" → Read `areas/people/john/summary.md`
- "What's the status of project X?" → Query `projects/X/items.json` for status category
- "What did I do last week?" → Search daily notes by date range
- "How do I prefer to brainstorm?" → Search tacit knowledge
- "List all active projects" → Glob `**/projects/*/summary.md`

## File Structure Reference

For detailed schema and format specifications, see [schema.md](references/schema.md).

**Quick reference**:
- Each entity has `summary.md` (overview) and `items.json` (facts array)
- Daily notes: `${PARA_MEMORY_ROOT:-~/para-memory}/memory/YYYY-MM-DD.md`
- Tacit knowledge: `${PARA_MEMORY_ROOT:-~/para-memory}/MEMORY.md`
- PARA categories: `projects/`, `areas/`, `resources/`, `archives/`
