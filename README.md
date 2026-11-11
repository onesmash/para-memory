# para-memory

Durable, structured memory for AI agents — atomic facts that are never deleted, only superseded, with a decay tier that decides what deserves attention now.

Built as two Agent Skills (write side and query side) plus a small set of Python scripts. No database, no service — memory lives as Markdown and JSON under `PARA_MEMORY_ROOT` (default `~/para-memory`).

## Why

Most agent memory is a chat log. It grows, it contradicts itself, and nothing tells you which fact is still current.

para-memory keeps **atomic facts** instead: one claim per entry, each with an id, a timestamp, a status, and a `supersededBy` pointer. When a fact changes you don't overwrite it — you mark it superseded and add the new one. The chain stays readable, so you can answer "what did we believe in March, and why did it change?" months later.

## Three layers

| Layer | What it holds | Where |
|---|---|---|
| **Knowledge graph** | Entities (projects / areas / resources / archives), each with `summary.md` (quick context) and `items.json` (atomic facts) | `entities/*/` |
| **Daily notes** | Chronological conversation timeline — the raw source facts are extracted from | `timeline/` |
| **Tacit knowledge** | One file of preferences and working style, updated as patterns emerge | `tacit/` |

Facts are grouped into **hot** (touched in 7 days), **warm** (30 days), **cold** (beyond). Decay is a *summary filter*: cold facts are omitted from `summary.md` so a quick context load stays small — but they remain in `items.json` and are still retrievable.

## Fact schema

```json
{
  "id": "entity-001",
  "fact": "Joined the company as CTO in March 2025",
  "category": "milestone",
  "timestamp": "2025-03-15",
  "source": "2025-03-15",
  "status": "active",
  "supersededBy": null,
  "relatedEntities": ["companies/acme", "people/jane"],
  "lastAccessed": "2026-01-28",
  "accessCount": 12
}
```

`status` is `active` or `superseded`; a superseded fact always carries the id of its replacement. Full field reference in [`skills/para-memory/references/schema.md`](skills/para-memory/references/schema.md).

## Quick start

```bash
export PARA_MEMORY_ROOT=~/para-memory   # where the store lives

# 1. initialise the store
python skills/para-memory/scripts/init_memory_system.py "$PARA_MEMORY_ROOT"

# 2. create an entity — category first, then name
#    categories map to sub-paths: projects → projects/,
#    people → areas/people/, companies → areas/companies/, resources → resources/
python skills/para-memory/scripts/create_entity.py companies acme
#    → $PARA_MEMORY_ROOT/knowledge/areas/companies/acme/

# 3. add a fact — the fact itself is JSON; `source` is required
python skills/para-memory/scripts/update_entity.py \
  "$PARA_MEMORY_ROOT/knowledge/areas/companies/acme" \
  --add '{"fact": "Signed the Series A in June 2025", "category": "milestone", "timestamp": "2025-06-01", "source": "2025-06-01"}'
#    → ✓ Added fact: acme-001

# 4. supersede an old fact — old id, then the replacement as JSON
python skills/para-memory/scripts/update_entity.py \
  "$PARA_MEMORY_ROOT/knowledge/areas/companies/acme" \
  --supersede acme-001 '{"fact": "Series A closed at $12M, not $8M", "category": "milestone", "timestamp": "2025-06-14", "source": "2025-06-14"}'
#    → ✓ Added fact: acme-002
#    → ✓ Superseded fact: acme-001 → acme-002

# 5. query — path is relative to knowledge/, so include the areas/ segment
bash skills/para-memory-query/scripts/query_entity.sh areas/companies/acme

#    timeline search takes a mode first: date | range | keyword
bash skills/para-memory-query/scripts/search_timeline.sh keyword Series
bash skills/para-memory-query/scripts/search_timeline.sh date 2025-06-01
bash skills/para-memory-query/scripts/search_timeline.sh range 2025-06-01 2025-06-30
```

Required fields for `--add` / `--supersede`: `fact`, `category`, `timestamp`, `source`. Everything else (`relatedEntities`, `lastAccessed`, `accessCount`) is filled in with defaults.

## Layout

```
skills/
  para-memory/          # write side
    SKILL.md            # skill contract: how an agent should use it
    references/
      schema.md         # every field of an atomic fact
      qmd_setup.md      # optional semantic search backend
    scripts/
      init_memory_system.py
      create_entity.py
      update_entity.py      # adds facts, supersedes facts
      save_chat_history.py  # writes conversation turns to the timeline
      weekly_synthesis.py   # regenerates summary.md by tier
      install_hooks.py      # hooks that capture conversations automatically
  para-memory-query/    # read side
    SKILL.md
    scripts/
      query_entity.sh
      search_timeline.sh
```

## Design decisions

**Facts are superseded, not deleted.** Keeping the chain costs a little space and buys an audit trail. Deleting a fact breaks any reference pointing at it.

**Decay filters summaries, not storage.** A cold fact is hidden from quick context, never dropped from the store. Retrieval by `query_entity.sh` still reaches it.

**Hooks capture automatically; the agent also writes explicitly.** `install_hooks.py` registers session-end hooks so conversations land in the timeline without the agent remembering to call anything. Facts still need an explicit `--add` — extraction is a judgement call, and a wrong fact that arrived silently is worse than a missing one.

**Optional semantic search, off by default.** `qmd_setup.md` describes wiring an external embedding backend. Without it, queries are keyword/grep over local files. If you configure one, note that index and query text leave the machine.

Structural changes to the layout go through the OpenSpec process in `openspec/`.

## Known limits

- **Decay uses creation date, not access.** `lastAccessed` is written at creation and **not** updated by queries, so `hot`/`warm`/`cold` currently reflects *age*, not usage. Frequency-based decay is designed but not wired.
- **`accessCount` has no write path.** It is set to 0 at creation and never incremented; the `>10` anti-decay rule is unreachable without editing JSON by hand.
- **Semantic retrieval is a placeholder.** Without a configured backend there is no vector path at all; with one, it is untested at scale.
- **No deletion API.** There is no way to physically remove a fact — supersession only. Any compliance requirement needing real erasure is not served today.
- **Summaries are model-generated and unchecked.** `weekly_synthesis.py` can summarise a fact wrongly; nothing verifies it against `items.json`.
- **`search_timeline.sh keyword` exits 1 on zero matches.** The script runs under `set -e`, so a `grep` with no hits terminates it with status 1 and no explanation. Treat exit 1 there as "no matches", not as a broken store.

These are documented rather than planned, so you can judge whether the tool fits before reading the code.

## License

MIT — see [LICENSE](LICENSE).
