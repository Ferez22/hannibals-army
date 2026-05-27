# Hannibal's Army — Master Plan

> Company intelligence system. Ingest files/URLs → LLM extracts entities → hybrid knowledge graph (SQLite + Chroma) → agents answer questions like "who owns X", "who was at Y event", "what's the policy on Z". MVP at QartMina, productized later.

---

## Project Structure

```
hannibals-army/
├── config.py                      # Model, staleness thresholds, vision budgets, palette
├── company-config.yml             # Living company metadata (gitignored, agent-updated)
├── company-config.sample.yml      # Template
├── digital-twin-config.yml        # Owner profile
├── main.py                        # TUI entry point
│
├── agents/
│   ├── base_agent.py              # BaseAgent + AgentResult
│   ├── hannibal.py                # LangGraph workflow + orchestrator persona
│   ├── ragnar.py                  # Ingestion
│   ├── cartographer.py            # Entity extraction + KG writes
│   ├── oracle.py                  # Query answering
│   └── donna.py                   # Validation, staleness, conflicts
│
├── capabilities/                  # Reusable functions agents call (not "skills" to avoid clash with Skill entity… which we dropped, but kept name clean anyway)
│   ├── parsers/
│   │   ├── pdf.py
│   │   ├── pptx.py
│   │   ├── image.py               # Gemma4 vision, variable token budget
│   │   └── url.py
│   ├── graph_store.py             # SQLite CRUD + recursive CTE traversal
│   ├── vector_store.py            # Chroma wrapper
│   ├── extractor.py               # LLM → entity/relation JSON
│   ├── dedup.py                   # Fuzzy match (rapidfuzz)
│   └── notifier.py                # TUI alert; Phase 4 adds Telegram/email
│
├── core/
│   ├── entity_types.py            # Pydantic models
│   ├── knowledge_graph.py         # Facade over graph_store + vector_store
│   └── ingestion_pipeline.py      # RAGNAR → CARTOGRAPHER → KG
│
├── tui/
│   ├── app.py
│   ├── theme.py
│   └── screens/                   # home, ingest, query, browser, review
│
├── db/graph.db                    # SQLite
└── memory/chroma/                 # Vectors
```

**Out of scope for now:** `mcp/` server (defer until external clients exist), `integrations/google_drive.py` (Phase 5 only).

---

## Knowledge Graph

### Entities (nodes)

| Entity | Key Fields |
|--------|-----------|
| `Person` | name, email, contact, tenure_since, expertise: list[str] |
| `Team` | name, mission, lead_id, domain, parent_team_id (nullable) |
| `Event` | name, date, type, outcome |
| `Document` | title, type, date, raw_path, ingested_at |
| `Rule` | category, title, content, owner_id, notify_person_id, valid_until |
| `Project` | name, status, team_id, started, target, description |

No `Skill` entity (use `Person.expertise` tags). No `Membership` node (it's an edge with properties).

### Edges

```
Person → MEMBER_OF        → Team       (props: role, tasks[], since, active)
Person → PARTICIPATED_IN  → Event
Person → AUTHORED         → Document
Team   → CHILD_OF         → Team       (parent/sub-team hierarchy)
Team   → RUNS             → Project
Event  → REFERENCES       → Document
Node   → EXTRACTED_FROM   → Document   (provenance — replaces source_documents field)
Rule   → OWNED_BY         → Person|Team
Rule   → NOTIFY           → Person
```

`MEMBER_OF` carries role + tasks per assignment → one person can have many memberships (Engineering/Developer doing weeklies, AI Club/Lead organizing sessions, Product Alpha/Associate writing specs).

### Memory fields (on every live node)

```python
created_at:       datetime
last_verified_at: datetime          # bumped on re-corroboration
source_count:     int               # distinct Documents that mention this entity
confidence:       float             # min(1.0, source_count/3) - 0.3 * contradiction_count, clamped [0,1]
```

**No stored `staleness_flag`.** Computed on read: `now() - last_verified_at > threshold_for(entity_type)`.

---

## Staging + Promotion (no auto-pollution)

Bad extractions never reach the live graph. Two-tier storage:

```
extraction → staging_nodes (all extracted, untrusted)
                 ↓ promotion gate (deterministic rules below)
              live_nodes (queried by ORACLE)
```

**Auto-promotion rules:**

| Entity | Auto-promote when | Else |
|--------|--------------------|------|
| Person | email present AND email passes domain filter (not `noreply@`, `info@`) | Pending screen |
| Team | seeded in `company-config.yml` OR mentioned in 3+ distinct documents | Pending |
| Project | has resolvable `lead_id` (links to live Person) AND mentioned in 2+ docs | Pending |
| Rule | extracted with explicit marker ("policy:", "must", "shall", category keyword) | Pending |
| Event | has both date AND name | Auto-promote |
| Document | always | Auto-promote |

**Staging schema mirrors live**, plus:
- `promotion_status`: `pending` | `auto_eligible` | `rejected`
- `blocked_reason`: `awaiting_corroboration` | `low_quality` | `duplicate_candidate` | `manual_review`
- `suggested_merge_into`: nullable live node_id (dedup candidate)

**Manual promotion** via TUI **Pending** screen. Actions: `Promote`, `Merge into X` (adds source to existing live), `Reject` (blacklist 90d), `Snooze` (re-eval next ingestion).

**ORACLE only queries live graph.** Staging invisible to user queries.

### Minimal system status

Single flag, no state machine:

```python
@dataclass
class SystemStatus:
    ingestion_paused: bool        # True when pending overload requires triage
    pending_count: int
    conflict_count: int
    last_health_check: datetime
```

`ingestion_paused = True` when `pending_count > 200` (auto) or user toggles. New ingestions reject with clear message until triaged.

---

## Agents

| Agent | Role |
|-------|------|
| **HANNIBAL** | LangGraph workflow root — routes user input to right agent, returns final response |
| **RAGNAR** | Takes file path or URL → returns `RawDocument` |
| **CARTOGRAPHER** | Takes `RawDocument` → LLM extracts entity/relation JSON → dedupes → writes to KG → updates `company-config.yml` |
| **ORACLE** | Takes NL question → hybrid search (vector → seed nodes, graph traversal → expand) → LLM synthesizes answer with cited nodes |
| **DONNA** | Staleness scan, conflict detection on writes, dispatches rule notifications |

```python
@dataclass
class AgentResult:
    success: bool
    data: Any
    cited_nodes: list[str] = []     # node ids for ORACLE traceability
    error: str | None = None

class BaseAgent:
    name: str
    persona: str
    kg: KnowledgeGraph
    def invoke(self, task: dict) -> AgentResult: ...
```

HANNIBAL is **not** a separate router on top of LangGraph — it **is** the LangGraph workflow, packaged with an orchestrator persona for user-facing messages.

---

## Memory & Forgetting

### Staleness thresholds (`config.py`)

| Entity Type | Days | Action when stale |
|-------------|-----:|-------------------|
| Person `MEMBER_OF` edges | 365 | Review queue |
| Team structure | 180 | Review queue |
| Project status | 90 | Review queue |
| Rule | 180 | **Direct notify owner via `NOTIFY` edge** |
| Event | — | Never stale |

### Conflict detection (explicit rules)

CARTOGRAPHER flags conflict when new extraction collides with existing node:

- **Person**: same name+email match → if any non-null field differs (role per team, expertise) → conflict
- **Rule**: same `title` match → if `content` differs (cosine similarity < 0.85) → conflict
- **Project**: same name → if `status` changed → not conflict, just status update + verified bump
- **Team**: same name → if `lead_id` or `parent_team_id` differs → conflict

On conflict: keep old node, write new candidate to `review_queue` table with both versions. Human resolves in Review screen.

### Decay flow

1. DONNA daily scan (on TUI startup + scheduled): for each node, compute staleness → if stale and not Rule → add to `review_queue`
2. Rules stale → DONNA looks up `NOTIFY` edge → calls `notifier.send(person, rule)` → person confirms/updates via TUI deep link or reply
3. New doc + conflict → CARTOGRAPHER puts candidate in `review_queue` (it does NOT auto-overwrite)
4. Human action in Review screen: `verify` (bump `last_verified_at`), `replace` (overwrite + bump), `delete`, `merge`

---

## TUI

**Framework:** Textual.

**Palette (`config.py`):**

```python
PALETTE = {
    "primary":   "#5BC8F5",   # light blue   — headers, agent names
    "text":      "#FFFFFF",   # white        — body
    "highlight": "#F5A623",   # orange       — selection, confidence
    "accent":    "#F5D020",   # yellow       — metadata, timestamps
    "danger":    "#E74C3C",   # red          — stale, conflicts, errors
    "success":   "#2ECC71",   # light green  — verified, success
    "dim":       "#4A5568",   # gray         — borders
    "bg":        "#0D1117",   # near black   — background
}
```

**Screens:**

| Screen | Content |
|--------|---------|
| Home | Status bar (READY / paused), pending/conflict counts, last 5 docs, quick query |
| Ingest | File path / URL input → live RAGNAR + CARTOGRAPHER progress log |
| Query | Chat with ORACLE, expandable "sources" panel showing cited live node ids |
| Browser | Live entity type filter, list, click → node + edges, confidence badge, stale indicator |
| Pending | Staged entities awaiting promotion: name + source snippet + suggested merges. Actions: Promote / Merge / Reject / Snooze |
| Review | Conflict queue (live vs new candidate, side-by-side diff) + staleness queue (non-rule) |

---

## Phase Roadmap

### Phase 0 — Scaffold (no logic)

**Output:** `python main.py` prints "Hannibal's Army ready (5 agents standing by)", all imports resolve, zero behavior.

- Strip trip planner: delete `tui_trip_planner.py`, `simple_tui_planner.py`, `mcp/destination_server.py`, `db/load_destinations.py`, `data/`, `trip_plans/`, `utils/`, `diagramms/`, `src/vector.py`, all trip docs
- Create directories: `agents/`, `capabilities/parsers/`, `core/`, `tui/screens/`
- `core/entity_types.py` — Pydantic models for 6 entities + edge property classes
- `agents/base_agent.py` — `BaseAgent`, `AgentResult`
- Stub each agent file: class + persona string + `invoke()` raising `NotImplementedError`
- `capabilities/graph_store.py` — class with empty methods, no SQL yet
- `capabilities/vector_store.py` — class with empty methods, no Chroma client yet
- `main.py` — imports everything, prints ready message
- Smoke test: `python -c "from agents.hannibal import HANNIBAL"` works

### Phase 0.5 — Extraction Prototype Spike

**Goal:** Measure Gemma4:e2b extraction quality on real QartMina docs before committing to architecture. Decides whether staging gates need tightening.

**Output:** Single throwaway script (`scripts/extraction_spike.py`), results document.

- Pick 5 representative QartMina documents (1 PDF, 1 PPTX, 1 image of org chart, 1 long URL, 1 short note)
- Hand-label expected entities/relations (ground truth)
- Run gemma4:e2b with extraction prompt → JSON
- Score: precision (extracted entities that match truth), recall (truth entities found), malformed-JSON rate
- **Decision gates:**
  - JSON validity ≥ 80% → continue to Phase 1
  - Precision ≥ 70% on Person+Team → staging gates sufficient
  - Recall ≥ 60% on Person+Team → acceptable; below = consider chunking change or bigger model role
- Document findings in `docs/EXTRACTION_BASELINE.md`

**No deps added.** Pure measurement.

---

### Phase 1 — Ingestion

**Output:** `python -m capabilities.parsers.pdf path/to/file.pdf` returns text. RAGNAR returns `RawDocument` for any supported format.

- `capabilities/parsers/pdf.py` (pymupdf), `pptx.py` (python-pptx), `url.py` (trafilatura), `image.py` (Gemma4 vision via Ollama, takes `token_budget` arg)
- `core/entity_types.py` adds `RawDocument` (source, format, raw_text, metadata, extracted_at)
- `agents/ragnar.py` — detects format from extension/MIME → calls right parser → returns `RawDocument`
- Sequential per file (parallelism deferred — see Open Decisions)

**Deps added:** `pymupdf`, `python-pptx`, `trafilatura`

### Phase 2 — KG Core + Extraction

**Output:** Feed 3 docs via CLI, ask "who is on engineering team?" via ORACLE, get cited answer.

- `capabilities/graph_store.py` — SQLite schema: `live_nodes`, `live_edges`, `staging_nodes`, `staging_edges`, `review_queue`, `pending_blacklist`. Recursive CTE for `CHILD_OF` traversal. All tables indexed on `(company_id, entity_type)`
- `capabilities/vector_store.py` — Chroma init with `paraphrase-multilingual-MiniLM-L12-v2`, only live nodes embedded
- `capabilities/extractor.py` — chunked input → LLM with `format="json"` → Pydantic validation → retry once on malformed
- `capabilities/dedup.py` — composite key match per entity type (see Dedup section), name normalization, returns existing live node id or None
- `capabilities/promotion.py` — applies promotion gates from rules table → moves staging → live atomically
- `core/system_status.py` — `SystemStatus`, pending_count threshold check, ingestion_paused flag
- `agents/cartographer.py` — extract → dedup → write to **staging** → run promotion check → eligible entities promoted, rest stay pending
- `agents/oracle.py` — embed question → top-K live vector hits → expand 1-2 hop via graph → LLM synthesize, prompt strictly bounded to cited nodes
- `core/knowledge_graph.py` — facade combining stores, exposes `live` and `staging` namespaces separately
- `core/ingestion_pipeline.py` — `ingest(source) → RAGNAR → CARTOGRAPHER`, rejects if `ingestion_paused`
- CARTOGRAPHER write-back to `company-config.yml` (only for promoted entities — teams, people, recent_events)
- Atomic YAML writes via `capabilities/yaml_io.py` (tmp + fsync + os.replace)

**Deps added:** `pydantic`, `rapidfuzz` (Chroma + langchain-chroma already in deps)

### Phase 3 — TUI v1

**Output:** Functional terminal app with 5 screens. Review screen scaffolded but disabled until Phase 4.

- `tui/theme.py` — Textual CSS using PALETTE
- `tui/app.py` — screen navigation, header status bar (state, pending count, conflicts, last ingest)
- Screens: Home, Ingest, Query, Browser, **Pending**
- Pending screen actions wired (Promote, Merge, Reject, Snooze) — promotion gates already exist from Phase 2
- Wire HANNIBAL as TUI entry point for user actions
- Auto-pause indicator in status bar when `ingestion_paused=True`

**Deps added:** `textual>=0.80.0`

### Phase 4 — DONNA + Conflicts + Staleness

**Output:** Stale entities surface, rules trigger direct notification, conflicts resolvable via UI.

- `capabilities/notifier.py` — TUI alert sink (Telegram/email behind feature flag)
- `agents/donna.py` — `scan_staleness()`, `detect_conflict(candidate, existing_live)` (per Conflict Detection rules), `dispatch_rule_notification(rule)`
- CARTOGRAPHER calls DONNA on every staging→live promotion attempt — conflicts route candidate to `review_queue` instead of promoting
- TUI Review screen wired: query review_queue (conflicts + non-rule staleness), action buttons → graph_store mutations
- Browser screen: confidence badge (orange), stale indicator (red, computed on read)
- DONNA write-back to `company-config.yml` (rule `last_verified_at`, `_meta.last_updated_by`)
- Health check job: monitors `pending_count`, sets `ingestion_paused` automatically on overload

### Phase 5 — Google Drive Ingestion

- `capabilities/integrations/google_drive.py` — OAuth flow, list/download files
- Drive folder selector in Ingest screen, sync button
- Pipeline: Drive file → RAGNAR → existing pipeline
- Optional: Sheets → structured import bypassing extractor (column headers → fields directly)

### Phase 6 — Productization (sequenced sub-phases)

- **6a** FastAPI exposing KG (read-only first)
- **6b** Multi-tenant: `company_id` foreign key on all nodes/edges, scope all queries
- **6c** Auth layer (API keys)
- **6d** Web UI (Streamlit or Next.js — decide later)

---

## Dependencies

**Already in `pyproject.toml`:** `langgraph`, `langchain[ollama]`, `langchain-chroma`, `pyyaml`, `python-dotenv`, `rich`

**To add per phase:**

| Phase | Adds |
|-------|------|
| 1 | `pymupdf`, `python-pptx`, `trafilatura` |
| 2 | `pydantic`, `rapidfuzz` |
| 3 | `textual` |
| 5 | `google-api-python-client`, `google-auth-oauthlib` |
| 6 | `fastapi`, `uvicorn` |

**Removed from earlier draft:** `networkx` (SQLite suffices), `pillow` (Gemma4 native), `mcp-client` (deferred).

---

## Resolved Decisions

- ✅ **Architecture** — staging + promotion gates (not state machine). Bad data can't reach live graph by construction.
- ✅ **Dedup composite keys** — per-entity (Person: email; Team: name+parent; Project: name+team_id; Rule: title fuzzy 0.9+; Event: name+date; Document: raw_path).
- ✅ **Name normalization** — deterministic pipeline before any matching ("Dr. John A. Smith Jr." → "john smith"). Variants tracked for soft-conflict detection, not auto-merge.
- ✅ **Person extraction guard** — auto-create only if email present AND passes domain filter. Otherwise staging.
- ✅ **Embedding model** — `paraphrase-multilingual-MiniLM-L12-v2` (DE/FR/EN support).
- ✅ **Chunking** — semantic-first (page/slide), then 1500 token max with 200 overlap. Each chunk inherits parent `Document.id`; multi-chunk mentions in same doc = 1 corroboration.
- ✅ **`company_id` from day 1** — env var, hardcoded "qartmina" default. Avoids Phase 6 retrofit.
- ✅ **Logging** — stdlib `logging` + RichHandler, file rotation, correlation ids via contextvars. Setup in `main.py`, not config.py.
- ✅ **YAML atomic writes** — tmp file + fsync + os.replace, via `capabilities/yaml_io.py`. Single-writer rule: CARTOGRAPHER writes content, DONNA writes `_meta`.
- ✅ **Confidence formula** — `min(1.0, source_count/3) - 0.3 * contradiction_count`, clamped [0,1]. Source = distinct Document.
- ✅ **HANNIBAL = LangGraph workflow** (not separate router).
- ✅ **`staleness_flag`** — computed on read, not stored.
- ✅ **No NetworkX** — SQLite + recursive CTEs.
- ✅ **No `Skill` entity** — use `Person.expertise: list[str]`.
- ✅ **No `Membership` node** — edge properties on `MEMBER_OF`.

## Open Decisions

- [ ] **ORACLE name** — keep, or rename (PYTHIA / SIBYL)?
- [ ] **Graph engine post-MVP** — SQLite now. Re-evaluate at >50k nodes or hot 3+ hop queries → Kuzu or Neo4j.
- [ ] **Ingestion parallelism** — sequential first. Async fan-out only when single-file latency proven slow.
- [ ] **Rule notification channels** — Phase 4 TUI-only. Telegram/email = Phase 4.1 if needed.
- [ ] **Vision token budget per task** — caller picks per parser. Defaults in `config.VISION_TOKEN_BUDGETS`.
- [ ] **Extraction prototype outcome** — depends on Phase 0.5 measurements. May require: bigger model for extraction role, regex backstop, or chunking changes.
