# CLAUDE.md — Hannibal's Army

> Repo guide for AI assistants. Read this first before making changes.

## What this project is

Company intelligence system. Ingest files (PDF/DOCX/XLSX/PPTX/images) and URLs → LLM extracts entities → hybrid knowledge graph (SQLite + Chroma vectors) → agents answer questions with citations. Local-first via Ollama + Gemma4:e2b. TUI built with Textual.

QartMina is the dog-food customer (single tenant). Multi-tenant productization deferred.

## Architecture

```
agents/         # 5 agents — Hannibal, Ragnar, Cartographer, Oracle, Donna
capabilities/   # Reusable functions agents call — parsers, stores, extractor, dedup, promotion, notifier, yaml_io/sync, chunker, photo_store
core/           # Domain — entity_types (Pydantic), knowledge_graph (facade), ingestion_pipeline, system_status
tui/            # Textual TUI — app + 9 screens
db/             # SQLite (graph.db) — gitignored
memory/chroma/  # Vector store — gitignored
data/samples/   # Test corpus — gitignored
data/photos/    # Person photos — gitignored
docs/           # ARMY_PLAN, ROADMAP, EXTRACTION_BASELINE, PHASE_*_*.md
```

## Agents

| Name | Role |
|------|------|
| HANNIBAL | Orchestrator (currently thin — placeholder for LangGraph routing) |
| RAGNAR | Ingestion — parses any supported format into RawDocument |
| CARTOGRAPHER | LLM extraction → staging → dedup → promotion → writes live KG + YAML mirror |
| ORACLE | Hybrid retrieval (entities + chunks) → cited answer. Summary mode for broad questions |
| DONNA | Validator — staleness scan, conflict detection, rule notifications (TUI + Telegram), auto-scan on startup if last > 24h |

## Key design decisions (DO NOT change without discussion)

1. **Staging + promotion gates** — bad extractions never reach live graph. ORACLE only queries live. Pending screen for manual triage.
2. **No state machine** — single `SystemStatus.ingestion_paused` flag. Auto-paused at `PENDING_AUTO_PAUSE_THRESHOLD=200`.
3. **Person.kind = employee | external | unknown** — `kind=unknown` blocks auto-promotion; user classifies in Pending with split buttons.
4. **emails as list[str]**, **sub_roles as list[str]** — auto-merge new emails (no conflict). Role conflict → Review with `Add as sub-role` / `Replace` actions.
5. **`MEMBER_OF` edge carries role + sub_roles + tasks + since** — not a separate node.
6. **No NetworkX, no MCP, no Skill entity** — keep it minimal. SQLite + recursive CTEs are enough.
7. **Vector embeddings** — `paraphrase-multilingual-MiniLM-L12-v2` (DE/FR/EN/AR). Two collections: `live_nodes` + `doc_chunks`.
8. **company_id on every row from day 1** — even single-tenant. Avoids Phase 6 retrofit.
9. **YAML write-back** — CARTOGRAPHER mirrors live KG into `company-config.yml` after every ingestion. Single-writer rule for that file.
10. **Conflict detection rules per entity** — explicit, in `agents/donna.py:detect_conflict`. Status changes on Project are NOT conflicts.
11. **Confidence formula** — `min(1.0, source_count / 3)`. Recomputed on every corroboration via `bump_corroboration`.

## Running

```bash
.venv/bin/python main.py              # full TUI
.venv/bin/python -m agents.ragnar <path-or-url>   # parser CLI test
.venv/bin/python scripts/age_nodes.py --type Person --days 400 --all  # test staleness
```

First run downloads sentence-transformers model (~120MB). KG init is in `main.warmup()` before Textual starts (sentence-transformers fork-subprocess fights Textual event loop otherwise).

## TUI keys

```
i ingest    q query     b browser   p pending   v review
e employees x externals t teams     a attach    g edges
r refresh   esc back    ctrl+c quit
```

## Config files

- `.env` — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`, `COMPANY_ID` (optional, defaults `qartmina`)
- `digital-twin-config.yml` — owner profile (gitignored)
- `company-config.yml` — auto-synced from KG, also seeded manually (gitignored). Template: `company-config.sample.yml`
- `config.py` — model names, paths, thresholds, palette, chunk sizes

## Schema migration policy

Current: **wipe + reingest** on any schema change. No alembic yet.

```bash
rm -rf db/graph.db memory/chroma
.venv/bin/python main.py
```

Adopt alembic when KG holds data we cannot rebuild from source files (Phase 12+).

## Testing

Manual TUI smoke tests + per-module Python `-c` checks. No automated test suite yet. Spike script `scripts/extraction_spike.py` measures extraction quality on `data/samples/`.

## What's done vs. coming

See `docs/ARMY_PLAN.md` (status) and `docs/ROADMAP.md` (next).

## Coding style

- Caveman mode in chat (terse). Code/commits/docs always normal English.
- Pydantic for domain models, dataclasses for ephemeral state.
- One agent per file. Capabilities are pure functions (no agent dependency).
- Errors quoted exactly in user-facing messages.
- TUI: `_set_options_preserve` pattern when refreshing Selects (don't lose user selection).
- Never call `refresh_all()` on Select.Changed / focus events — only on actual state mutation.

## Risks the AI should not ignore

1. Gemma4:e2b is small. Extraction quality ~70% on Person, lower on relations. Conflict-aware staging absorbs this.
2. Multilingual embedder loses some recall on Arabic. Real fix = transliteration pass + multilingual re-rank.
3. Sentence-transformers subprocess fork breaks Textual on Python 3.13 — keep `OMP_NUM_THREADS=1`, `TOKENIZERS_PARALLELISM=false` in main.py.
4. Telegram notifier swallows network errors (best-effort). Don't make scan blocking on it.
5. ORACLE summary mode triggers on keyword match. Sometimes misclassifies. Acceptable for MVP.
