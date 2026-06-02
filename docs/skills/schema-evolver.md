# Skill: Schema Evolver

> Checklist for safely changing entity types, edge types, or DB schema in Hannibal's Army.

## When to use

- Adding a field to a Pydantic entity model
- Adding a new entity type
- Adding a new edge type
- Changing a field shape (str → list, list → dict, etc)
- Renaming a field
- Adding a new SQLite table

## Why this skill matters

Phase 9.1 touched 13 files for one model change. Miss any one and downstream views break silently (e.g., yaml_sync stops writing the new field, Pending detail shows the old shape, ORACLE never retrieves the new field).

## The Checklist

### Adding a new field to an existing entity

For each new field:

- [ ] `core/entity_types.py` — add to Pydantic model with default
- [ ] `agents/cartographer.py:_to_storage_fields` — set default value when extracted
- [ ] `agents/cartographer.py:_entity_description` — include in vector embedding text
- [ ] `capabilities/extractor.py:EXTRACTION_PROMPT` — if extractor should produce it: add to schema example + define semantics
- [ ] `capabilities/dedup.py:find_existing_*` — does this field affect matching?
- [ ] `capabilities/promotion.py:should_auto_promote` — does this field gate promotion?
- [ ] `agents/donna.py:detect_conflict` — does mismatch on this field = conflict, auto-merge, or update?
- [ ] `capabilities/yaml_sync.py:_build_*` — mirror field into company-config.yml
- [ ] `tui/screens/browser.py:on_row` — include in detail pane
- [ ] `tui/screens/pending.py:_friendly_detail` — friendly format for the new field
- [ ] Any entity-specific TUI screen (Employees, Externals, Clients, etc) — render the new field
- [ ] If field is editable: update edit form in the relevant screen
- [ ] `CLAUDE.md` — note new field in "Key design decisions" if it's behaviour-changing

### Adding a new entity type (e.g., Client in Phase 9.1)

- [ ] All of the above for each field
- [ ] `core/entity_types.py` — full model
- [ ] `agents/cartographer.py:_TYPE_MAP` — register key → type
- [ ] `agents/cartographer.py:_to_storage_fields` — storage shape
- [ ] `agents/cartographer.py:_entity_description` — description for vector embed
- [ ] `capabilities/extractor.py:EXTRACTION_PROMPT` — add definition + schema example
- [ ] `capabilities/extractor.py:EMPTY_RESULT` — include new key with `[]`
- [ ] `capabilities/dedup.py` — add `find_existing_<entity>` + register in `FINDERS`
- [ ] `capabilities/promotion.py:should_auto_promote` — new branch
- [ ] `agents/donna.py:_TYPE_TO_THRESHOLD` — staleness threshold key
- [ ] `config.py:STALENESS_THRESHOLDS` — set value
- [ ] `agents/donna.py:detect_conflict` — conflict rules
- [ ] `agents/donna.py:_scan_count` — entity loop, counts dict
- [ ] `agents/donna.py:_scan_staleness` — entity loop
- [ ] `capabilities/yaml_sync.py` — `_build_<entity>s()` function + register in `sections_written`
- [ ] `tui/screens/browser.py:ENTITY_TYPES` — add to list
- [ ] `tui/screens/edges.py:populate_selects` — include in entity-fetch loop
- [ ] `tui/screens/pending.py:_friendly_detail` — friendly branch
- [ ] `tui/screens/home.py` — counts loop includes new type
- [ ] Optional: dedicated screen if entity has its own visual treatment (Employees, Clients, etc)
- [ ] `tui/app.py:SCREENS` + `BINDINGS` — wire key shortcut if new screen
- [ ] `tui/theme.py` — card style if new screen has cards
- [ ] `CLAUDE.md` — update entity table

### Adding a new edge type

- [ ] `core/entity_types.py:EdgeType` — add to Literal union
- [ ] `capabilities/extractor.py:EXTRACTION_PROMPT` — list in edge types section
- [ ] `tui/screens/edges.py:EDGE_TYPES` — add to dropdown
- [ ] Any side-effect on field sync (e.g., OWNED_BY Project→Client also sets Project.client_id) — handle in edges.py:create_edge
- [ ] Downstream views that read this edge — Clients screen, Employees card, ORACLE retrievers
- [ ] `CLAUDE.md` — note new edge if it's a primary relation

### Adding a new SQLite table

- [ ] `capabilities/graph_store.py:DDL` — schema with indexes
- [ ] Bump `SCHEMA_VERSION`
- [ ] CRUD methods on `GraphStore`
- [ ] Facade methods on `KnowledgeGraph` if used by agents
- [ ] **Wipe + reingest workflow documented in user-facing message**

### Renaming a field

Use this pattern (don't lose data):

1. Add new field alongside old field
2. In `_to_storage_fields`: write to both during transition period
3. In all readers: prefer new, fall back to old
4. After confirming all live data uses new field: remove old field references
5. Drop old field from Pydantic model
6. Optional cleanup: `UPDATE live_nodes SET fields_json = ...` to strip old key

### Changing field shape (str → list, etc)

- [ ] All readers must handle BOTH shapes during transition (`emails` = old single string OR new list)
- [ ] `_to_storage_fields`: convert old → new shape
- [ ] dedup logic: handle both shapes
- [ ] After confirmation: remove old-shape handling

See `capabilities/dedup.py:find_existing_person` for the pattern when we migrated `email` → `emails`.

## Migration policy

| When | What |
|------|------|
| Phase 0-3 (prototype) | Wipe DB + reingest, no migration code |
| Phase 4-7 (MVP) | Same — `rm -rf db/graph.db memory/chroma` |
| Phase 9+ (in production-ish) | Backward-compat readers (handle missing fields) |
| Phase 12+ (real data) | Alembic + explicit migrations |

For current state: backward-compat readers are best practice. Defaults in Pydantic + `.get(key, default)` everywhere.

## Test after a schema change

1. `.venv/bin/python -c "from core.entity_types import *; print('ok')"`
2. Instantiate the changed model with minimal fields
3. Run promotion gate test for each variant
4. `rm -rf db/graph.db memory/chroma` if migration not coded
5. Restart TUI, ingest a sample, verify it appears correctly in:
   - Home counts
   - Browser detail
   - Relevant entity screen (Employees / Clients / etc)
   - Pending if it didn't auto-promote
   - `company-config.yml`
6. Query ORACLE — does the new field surface in answers?
