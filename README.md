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
| **Daily notes** | Chronological conversation timeline — the raw source facts are extracted from | `memory/` (`<date>.md` or `<date>-<shortid>-session.md`) |
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
python3 skills/para-memory/scripts/init_memory_system.py "$PARA_MEMORY_ROOT"

# 2. create an entity — category first, then name
#    categories map to sub-paths: projects → projects/,
#    people → areas/people/, companies → areas/companies/, resources → resources/
python3 skills/para-memory/scripts/create_entity.py companies acme
#    → $PARA_MEMORY_ROOT/knowledge/areas/companies/acme/

# 3. add a fact — the fact itself is JSON; `source` is required
python3 skills/para-memory/scripts/update_entity.py \
  "$PARA_MEMORY_ROOT/knowledge/areas/companies/acme" \
  --add '{"fact": "Signed the Series A in June 2025", "category": "milestone", "timestamp": "2025-06-01", "source": "2025-06-01"}'
#    → ✓ Added fact: acme-001

# 4. supersede an old fact — old id, then the replacement as JSON
python3 skills/para-memory/scripts/update_entity.py \
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
      save_chat_history.py  # captures a session to memory/<date>-<id>-session.md
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

**Hooks capture automatically; the agent also writes explicitly.** `install_hooks.py` registers session-end hooks so conversations land in `memory/` without the agent remembering to call anything. Re-running the hook re-renders the whole file from the transcript, so a long session never keeps only its first turn. Facts still need an explicit `--add` — extraction is a judgement call, and a wrong fact that arrived silently is worse than a missing one.

**Optional semantic search, off by default.** `qmd_setup.md` describes wiring an external embedding backend. Without it, queries are keyword/grep over local files. If you configure one, note that index and query text leave the machine.

Structural changes to the layout go through the OpenSpec process in `openspec/`.

## Write-path invariants (formally checked)

Three sentences, as required by the S5 close-out: what the property is, which command re-runs it, and how far it is covered.

1. **Property.** One `--supersede` either commits *all* of its changes (new fact present, old fact `superseded`, `supersededBy` pointing at the new id) or none of them — a crash must never leave two `active` facts with no pointer. Two concurrent `--add` on the same entity must both survive, and fact ids must not collide.
2. **Re-run.** `bash spec/run.sh` — works from a clean shell; exits `0` when both properties hold and both destruct variants go red, `1` on any mismatch, `2` when the toolchain is missing (never a silent pass).
3. **Coverage.** `spec/` models the write path of `update_entity.py`; the counterexample-to-test bridge lives in `tests/test_write_path.py`. The sync commit is recorded in [`spec/PROPERTY-REGISTER.md`](spec/PROPERTY-REGISTER.md).

The capture, query and synthesis paths are guarded by ordinary unit tests instead of invariants:
`python3 -m unittest discover -s tests` runs the whole guard suite (32 tests), and
`python3 tests/destruct_variants.py` re-breaks each fixed defect one at a time and requires the
matching test to go red — a green suite that no change can turn red proves nothing.

`spec/ParaMemory.tla` is the target design (one lock per entity, one atomic commit per operation). `ParaMemoryLostUpdate.tla` reproduces the old unlocked snapshot-overwrite race; `ParaMemoryPartial.tla` reproduces the old two-write supersede with a crash window. Both go red for their own reason.

## Known limits

- **Decay uses creation date, not access.** `lastAccessed` is written at creation and **not** updated by queries, so `hot`/`warm`/`cold` currently reflects *age*, not usage. Frequency-based decay is designed but not wired.
- **`accessCount` has no write path.** It is set to 0 at creation and never incremented; the `>10` anti-decay rule is unreachable without editing JSON by hand.
- **Semantic retrieval is a placeholder.** Without a configured backend there is no vector path at all; with one, it is untested at scale.
- **No deletion API.** There is no way to physically remove a fact — supersession only. Any compliance requirement needing real erasure is not served today.
- **Summaries are model-generated and unchecked.** `weekly_synthesis.py` can summarise a fact wrongly; nothing verifies it against `items.json`.
- **Query scripts can't tell "nothing found" from "broken" for every mode.** The keyword mode was fixed:
  zero matches now prints `No matches found` and exits `0` (`tests/test_query_scripts.py` locks it).
  `date` matches every note whose filename starts with that day (`<date>.md` and every
  `<date>-<id>-session.md`), so a captured session is reachable by its date; `date`/`range` still exit `1`
  when the day genuinely has no note — that is "you asked for a date that isn't there", not an empty search.

These are documented rather than planned, so you can judge whether the tool fits before reading the code.

## License

MIT — see [LICENSE](LICENSE).
