# CLAUDE.md — Hannibal's Army

> Repo guide for AI assistants. Read this first before making changes.

## Skills (read first when relevant)

- [Prompt engineer](docs/skills/prompt-engineer.md) — extractor / ORACLE / Telegram intent prompts
- [TUI UX designer](docs/skills/ux-ui-designer.md) — layout, Select preservation, banner patterns
- [Schema evolver](docs/skills/schema-evolver.md) — checklist for entity / edge / table changes
- [Agentic tester](docs/skills/agentic-tester.md) — validation sequence per phase

## What this project is

Company intelligence system. Ingest files (PDF/DOCX/XLSX/PPTX/images) and URLs → LLM extracts entities → hybrid knowledge graph (SQLite + Chroma vectors) → agents answer questions with citations. Local-first via Ollama + Gemma4:e2b. TUI built with Textual.

QartMina is the dog-food customer (single tenant). Multi-tenant productization deferred.

## Architecture

```
agents/         # Hannibal, Ragnar, Cartographer, Donna + ORACLE split: oracle (entry) → oracle_intent (LLM+lexical router) → oracle_retrieve (per-intent retrievers) → oracle_synth (local Ollama or OpenAI cloud)
capabilities/   # parsers, graph_store, vector_store, extractor, dedup, promotion, notifier, yaml_io/sync, chunker, photo_store, retriever, llm, text_render (markdown), telegram_bot (polling+dispatch), config_patch (CEO edit flow)
core/           # Domain — entity_types (Pydantic), knowledge_graph (facade), ingestion_pipeline, system_status
tui/            # Textual TUI — app + 9 screens
db/             # SQLite (graph.db) — gitignored
memory/chroma/  # Vector store — gitignored
data/samples/   # Test corpus — gitignored
data/photos/    # Person photos — gitignored
docs/           # ARMY_PLAN, ROADMAP, EXTRACTION_BASELINE, PHASE_*_*.md, graph-datastructure.dbml
```

## Agents

| Name | Role |
|------|------|
| HANNIBAL | Orchestrator (currently thin — placeholder for LangGraph routing) |
| RAGNAR | Ingestion — parses any supported format into RawDocument |
| CARTOGRAPHER | LLM extraction → staging → dedup → promotion → writes live KG + YAML mirror |
| ORACLE | Intent router → per-intent retriever → synthesizer. Intents: `person`, `project`, `team`, `client`, `summary`, `config_edit`, `generic`. Lexical patterns in `oracle_intent.py:LEXICAL_PATTERNS` fast-path; LLM classifier fallback. Synthesis auto-switches to OpenAI when `OPENAI_API_KEY` set, else local Ollama. |
| SENTINEL | Tier classifier (Phase 10B). Runs post-extraction in `core/ingestion_pipeline.py`. Two-stage: rule signals first (`capabilities/tier_classify.py:RULE_SIGNALS`), LLM fallback on miss. Writes `doc_kind`, `tier`, `tier_reason` to live Document. `tier_confirmed_*` stays empty until admin confirms in Browser. |
| DONNA | Validator — staleness scan, conflict detection, rule notifications (TUI + Telegram), auto-scan on startup if last > 24h |

## Key design decisions (DO NOT change without discussion)

1. **Staging + promotion gates** — bad extractions never reach live graph. ORACLE only queries live. Pending screen for manual triage.
2. **No state machine** — single `SystemStatus.ingestion_paused` flag. Auto-paused at `PENDING_AUTO_PAUSE_THRESHOLD=200`.
3. **Person.kind = employee | external | unknown** — `kind=unknown` blocks auto-promotion; user classifies in Pending with split buttons.
4. **Project.kind = internal | external** — external requires `client_id`. Team.kind = internal | external — external requires `external_org`. Kind change is a conflict (identity-level).
5. **Client entity always external** — paying customer orgs. Promotion gate is `awaiting_validation` (CEO confirms; money-touching).
6. **emails as list[str]**, **sub_roles as list[str]** — auto-merge new emails (no conflict). Role conflict → Review with `Add as sub-role` / `Replace` actions.
7. **`MEMBER_OF` edge carries role + sub_roles + tasks + since** — not a separate node.
8. **Edge ↔ field sync rule** — `OWNED_BY` Project→Client edge also sets `Project.client_id` field + flips `Project.kind` to external. Downstream readers (Clients screen, yaml_sync) read both edge AND field for robustness. Pattern in `tui/screens/edges.py:create_edge`.
9. **No NetworkX, no MCP, no Skill entity** — keep it minimal. SQLite + recursive CTEs are enough.
10. **Vector embeddings** — `paraphrase-multilingual-MiniLM-L12-v2` (DE/FR/EN/AR). Two collections: `live_nodes` + `doc_chunks`.
11. **company_id on every row from day 1** — even single-tenant. Avoids Phase 6 retrofit.
12. **YAML write-back is canonical** — `company-config.yml` is the single source of truth. CARTOGRAPHER mirrors live KG into it after every ingestion. `_meta.edit_history` audits every write (CARTOGRAPHER syncs, DONNA scans, init_script bootstraps, CEO edits). Single-writer rule per section: `identity / leadership / tools / culture` are human-curated; `teams / people / projects / clients / rules / recent_events` are agent-mirrored.
13. **Conflict detection rules per entity** — explicit, in `agents/donna.py:detect_conflict`. Status changes on Project are NOT conflicts. kind changes ARE.
14. **Confidence formula** — `min(1.0, source_count / 3)`. Recomputed on every corroboration via `bump_corroboration`.
15. **ORACLE intent router is two-stage** — fast lexical regex in `oracle_intent.py:LEXICAL_PATTERNS` first; only falls through to LLM classifier on no match. When adding new question shapes, prefer extending lexical patterns over re-prompting the classifier.
16. **CEO config edits via Telegram are gated** — `config_edit` intent produces a YAML patch proposal with inline buttons (confirm/cancel). `capabilities/config_patch.py` applies the patch with `_meta.edit_history` audit. Never write to `company-config.yml` from Telegram without CEO callback confirmation.
17. **Telegram identity** — `Person.telegram_chat_id` resolves the sender. `/register` command binds chat → person. Unknown chats only get a generic refusal; never expose KG content without resolution.
18. **Tier pyramid (Phase 10A)** — `ceo < c_level < director < manager < everyone`. Lower rank = more access. `config.TIERS` + `tier_rank()`. Adding tier = append + remap. Storage uses label strings; comparison via rank at query time.
19. **Default tier on ambiguous docs = `director`** — conservative. Over-restrict beats leak. Unconfirmed-tier docs (`tier_confirmed_by` unset) are visible only to CEO + owner.
20. **Sender resolution failure → `UNKNOWN_SENDER_TIER` (everyone)** — Telegram chat without resolved Person gets baseline tier. `/register` mandatory before tier elevation. Admin chat is always `ceo` tier regardless of Person resolution.
21. **Tier filter lives in `capabilities/retriever.py:_tier_filter`** — chunks post-filtered against `live_nodes.fields_json` for tier + owner_id. Threaded through ORACLE via `sender_tier_rank` + `sender_person_id` in retrieve ctx. Ownership beats tier (owner sees own docs regardless).
22. **Tier confirmation is CEO-gated in Pending** — `tui/screens/pending.py` exposes tier `Select`; `_promote_person` writes `tier` + `tier_confirmed=True` only at promotion time.
23. **SENTINEL runs at ingest, not retrieval (Phase 10B)** — tier proposal baked into Document fields after CARTOGRAPHER extracts, before chunk-embed. Rules-first (deterministic) then LLM fallback. Admin reviews + confirms in Browser tier picker. Re-classify requires re-ingest.
24. **Document confirmation lives in Browser, not Pending** — Documents auto-promote to live (chunking depends on it). Browser detail surfaces SENTINEL proposal + tier picker + Confirm button. Until confirmed, `_tier_filter` gates the doc to CEO + owner only.
25. **SENTINEL learning loop (Phase 10B.6–10B.8)** — every Browser tier confirmation writes to `tier_corrections` SQLite table via `capabilities/tier_memory.py`. Embedding (sentence-transformers MiniLM) stored as float32 BLOB. On next ingest, SENTINEL pulls top-K (`TOPK_FEWSHOT=5`) nearest past corrections by cosine and injects them as few-shot examples in the LLM prompt. Rules path is unaffected. Confirmations are recorded regardless of agreement; only disagreements set `is_override=1`.
26. **Lazy reason capture** — Browser confirm is silent when CEO picks SENTINEL's tier. When tiers differ, an `Input` appears and reason is required before the override is applied. Reasons feed back into the few-shot prompt to teach the model *why* a class of docs is reclassified.
27. **Rule mining is stub-only in 10B** — `tier_memory.mine_rule_candidates()` aggregates overrides per tier and finds repeating title n-grams (≥3 support). Not auto-applied; surfaced for manual CEO confirmation in a future TUI screen (deferred to Phase 11+).

## Running

```bash
.venv/bin/python main.py                          # full TUI
.venv/bin/python main.py --with-bot               # TUI + Telegram bot polling loop (background thread)
.venv/bin/python -m agents.ragnar <path-or-url>   # parser CLI test
.venv/bin/python scripts/age_nodes.py --type Person --days 400 --all  # test staleness
.venv/bin/python scripts/init_company.py                              # bootstrap company-config.yml
.venv/bin/python scripts/extraction_spike.py                          # regression measure on sample docs
```

First run downloads sentence-transformers model (~120MB). KG init is in `main.warmup()` before Textual starts (sentence-transformers fork-subprocess fights Textual event loop otherwise).

## TUI keys

```text
i ingest    q query     b browser   p pending   v review
e employees x externals c clients   t teams     a attach    g edges
r refresh   esc back    ctrl+c quit
```

## Config files

- `.env` — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`, `COMPANY_ID` (optional, defaults `qartmina`), `OPENAI_API_KEY` (Phase 9.2+ for synthesis auto-switch)
- `digital-twin-config.yml` — owner profile (gitignored)
- `company-config.yml` — **canonical company-of-record**. Auto-mirrored from KG by CARTOGRAPHER. Seeded by `scripts/init_company.py`. Sections: human-curated (identity, leadership, tools, culture) vs agent-mirrored (teams, people, projects, clients, rules, recent_events). `_meta.edit_history` audits every write. Template: `company-config.sample.yml`
- `config.py` — model names, paths, thresholds, palette, chunk sizes, vision budgets, auto-scan interval

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
6. ORACLE synthesis silently routes to OpenAI when `OPENAI_API_KEY` is set — sensitive KG content leaves the box. Strip the key in `.env` to force local-only.
7. Telegram bot runs in a background thread when `--with-bot`. It shares the KG handle; long-running CEO patches must not block the polling loop (use the dispatch pattern in `capabilities/telegram_bot.py`).
8. Markdown rendering split: Telegram uses HTML subset (`capabilities/text_render.py:to_telegram_html`); TUI uses Rich Markdown. Same source string; do not embed Telegram-specific tags in answers.
9. Tier filter is enforced on chunks only (Phase 10A). Entity-level retrieval (Persons, Projects, etc.) is NOT yet tier-filtered. Phase 10B+ extends to entities. For now, KG entity facts are visible to all senders; only document chunks are gated.
10. Pre-10A legacy docs in `db/graph.db` lack tier metadata → treated as `director` unconfirmed → visible only to CEO + owner. Wipe + reingest (or one-off SQL migration) before broader manager rollout.
