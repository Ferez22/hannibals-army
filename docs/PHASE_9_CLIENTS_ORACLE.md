# Phase 9 — Clients, Project Hierarchy, ORACLE Rebuild, Telegram CEO

> Restructures the data model to handle real client work, rebuilds ORACLE around
> intent routing + clarification, brings Telegram inbound with CEO-gated config
> editing, and treats `company-config.yml` as the canonical company-of-record.

---

## Decisions locked

| # | Decision |
|---|----------|
| D1 | `Project.kind = "internal" | "external"`. External projects MUST have a `client_id`. Internal projects have none. |
| D2 | One Project → one Client max |
| D3 | Multiple Teams per Project (internal + external partner allowed) |
| D4 | Person can be assigned to Project directly AND via Team |
| D5 | No sub-projects in MVP |
| D6 | QartMina = the company. Lives in `company-config.yml`. No self-Client trick |
| D7 | Clarification UI = buttons (Textual Button widgets, dynamic) |
| D8 | Auto-switch synthesis model. `rule` and `project` intents → OpenAI GPT-5.4-mini if `OPENAI_API_KEY` present. Other intents → Gemma4:e2b |
| D9 | Chunks shrink 1200 → 500 chars on next ingest |
| D10 | company-config initialization via one-shot CLI script (`scripts/init_company.py`) |
| D11 | Telegram CEO auth via `Person.telegram_chat_id` + role check |
| D12 | `_meta.edit_history` audit trail in company-config.yml |

---

## Data model changes

### NEW: Client

```python
class Client(MemoryFields):
    id: str
    company_id: str
    name: str
    industry: str | None
    contact_person_id: str | None   # FK to a Person (external)
    contact_email: str | None
    domicile: str | None
    status: Literal["active", "paused", "closed"] = "active"
    notes: str | None
```

### CHANGED: Project

```python
class Project(MemoryFields):
    id: str
    company_id: str
    name: str
    kind: Literal["internal", "external"] = "internal"   # NEW
    status: str | None
    client_id: str | None       # NEW — required when kind=external
    started: str | None
    target: str | None
    description: str | None
```

### CHANGED: Team

```python
class Team(MemoryFields):
    id: str
    company_id: str
    name: str
    kind: Literal["internal", "external"] = "internal"   # NEW
    external_org: str | None    # NEW — required when kind=external
    mission: str | None
    lead_id: str | None
    domain: str | None
    parent_team_id: str | None
```

### CHANGED: Person

```python
class Person(MemoryFields):
    # ...existing fields...
    telegram_chat_id: str | None = None   # NEW — for Telegram bot auth
```

### Edges added

```
Project   → OWNED_BY            → Client     (required for external projects)
Team      → WORKS_ON            → Project    (props: scope, since, role)
Person    → WORKS_ON            → Project    (props: role, allocation_pct)
Person    → BELONGS_TO_CLIENT   → Client     (external persons tied to a client)
```

### Promotion gates (Person already complex; updated table)

| Entity | Auto-promote when | Else |
|--------|-------------------|------|
| Client | name + status set | Pending (reason: `awaiting_validation`) |
| Project (internal) | name + status set | Pending |
| Project (external) | name + status + client_id resolved | Pending |
| Team (internal) | name set OR seeded in config | Pending |
| Team (external) | name + external_org set | Pending |

### Conflict detection additions

```python
# Client
- name match + status different → status update (not conflict)
- name match + domicile different → conflict

# Project
- name match + kind different → conflict
- name match + client_id different → conflict
- status change → update, not conflict (existing rule)

# Team
- name match + kind different → conflict
- name match + external_org different → conflict
```

---

## company-config.yml lifecycle

### Sections

| Section | Writer | Read by |
|---------|--------|---------|
| `_meta` | CARTOGRAPHER, DONNA, init script, Telegram CEO edits | everyone |
| `_meta.edit_history` (NEW) | every writer appends | audit |
| `identity` | init script + Telegram CEO edits | ORACLE (intent=`culture`/`company`) |
| `leadership` | init script + Telegram CEO edits + CARTOGRAPHER when promoted Person is CEO/CTO/HR | ORACLE |
| `teams` | CARTOGRAPHER (mirror of live Teams) | ORACLE, init script reads |
| `people` | CARTOGRAPHER (mirror) | ORACLE |
| `projects` | CARTOGRAPHER (mirror) | ORACLE |
| `clients` | CARTOGRAPHER (mirror) — NEW | ORACLE |
| `rules` | CARTOGRAPHER (mirror) | ORACLE |
| `recent_events` | CARTOGRAPHER (mirror, last 10) | ORACLE |
| `tools` | init script + Telegram CEO edits | ORACLE |
| `culture` | init script + Telegram CEO edits | ORACLE (intent=`culture`) |

### `_meta.edit_history` format

```yaml
_meta:
  last_updated_by: CARTOGRAPHER
  last_updated_at: '2026-05-31T18:00:00'
  schema_version: '1.1'
  edit_history:
    - {ts: '2026-05-31T18:00:00', by: 'CARTOGRAPHER', action: 'sync', sections: ['people', 'teams']}
    - {ts: '2026-05-31T16:30:00', by: 'CEO:Fares', action: 'edit', path: 'identity.hq', from: '—', to: 'Immeuble Mazars, 1 Rue du Lac Ghar el Melh, La Marsa Tunis'}
    - {ts: '2026-05-30T09:00:00', by: 'init_script', action: 'create', sections: ['identity', 'leadership', 'tools', 'culture']}
```

Cap at last 100 entries to prevent unbounded growth.

---

## ORACLE rebuild

### Architecture

```
question
   ↓
intent_classifier (lexical + LLM-fallback)
   ↓
   ├─ if needs_clarification → reply with clarification + suggestion buttons
   └─ else → per_intent_retriever
                   ↓
                synthesizer (gemma4 OR gpt-5.4-mini per intent + config)
                   ↓
                AgentResult(answer, citations, diag)
```

### Intent classifier — output schema

LLM is asked to return strict JSON:

```json
{
  "intent": "person | team | project | client | rule | event | document | culture | summary | unclear",
  "entities_referenced": ["Additionality", "Fares"],
  "needs_clarification": false,
  "clarification_q": null,
  "suggestions": []
}
```

Lexical fast-path triggers (skip LLM call):

| Pattern | Intent |
|---------|--------|
| `^who is /^who works on / contact for ` | person |
| `^what does (the )?(team|engineering|hr) ` | team |
| `^status of / lead of / who runs ` | project |
| `^(list )?(our )?clients` | client |
| `policy on / our rule for / how do we / how to handle / whistleblowing` | rule |
| `(values|culture|working style|company about|domiciliated|hq|address|location)` | culture |
| `^(tell me about|overview|summarize|describe)` | summary |
| (vague: "what's important", "anything new", "help me") | unclear |

Anything else → LLM classifier.

### Per-intent retrievers

| Intent | Retrieval |
|--------|-----------|
| `person` | Resolve name → Person node + ALL edges + neighbor nodes (Team, Project, Client) + top-3 chunks mentioning name |
| `team` | Resolve team name → Team + members (via MEMBER_OF) + projects (via WORKS_ON) + sub-teams (CHILD_OF) |
| `project` | Resolve project name → Project + Client (if external) + Teams (WORKS_ON) + direct Persons (WORKS_ON) + status + top-5 chunks |
| `client` | Resolve client → Client + linked Projects + external Persons (BELONGS_TO_CLIENT) |
| `rule` | Vector search Rules (k=10) + heavy chunk search (k=8) — policy answers need source text |
| `event` | Event nodes filtered/sorted by date + chunks mentioning event |
| `document` | Chunk search dominant (k=10) + Document metadata |
| `culture` | `company-config.yml` (identity + culture + leadership + tools) + Rule nodes filtered by category=value |
| `company` | NEW — strictly `company-config.yml.identity` + `leadership`. Triggered by "our company", "the company", "us", "we", or the self-company name (e.g. "qartmina") in question |
| `summary` | Full inventory (current behavior preserved) |
| `unclear` | RETURN clarification — no retrieval |

### Self-company resolution (must-have for 9.2 — validation surfaced bug)

When user mentions "the company", "our company", "us", "we", "this company", OR the name from `company-config.yml.identity.name`:

1. Route to `company` intent BEFORE `client` intent (priority order in classifier)
2. Retrieve from `company-config.yml.identity` + `leadership` + `culture` + `tools`
3. Never resolve "the company" to a Client just because Client chunk had high cosine
4. Helper: `is_self_company(text: str) -> bool` in `oracle_intent.py` — checks against `config.COMPANY['identity']['name']` + aliases

Prompt for `company` intent synthesis MUST distinguish:
- "the company we work WITH" → Client
- "the company we ARE" → self (from `company-config.yml`)

Bug observed during 9.1.5 validation:
- Q: "what is the address" → returned OpenAI's address (extracted from contract)
- Q: "what is qartmina and what projects do they work on" → summary mode listed BE QARTMINA.pdf + project but missed identity info
- Q: "where is the company domiciliated" → mixed contract chunks, hallucinated partial address

Fix paths: routing + retrievers above + explicit prompt anchoring to `company-config.yml.identity` block.

### Clarification reply

When `needs_clarification=true`:
- `AgentResult.data = {"answer": "Could you narrow down?", "suggestions": ["ongoing project status", "stale rules", "open conflicts", "pending tasks"]}`
- Query screen renders each suggestion as a Button
- Click button → re-submits as new question

### Stricter synthesis prompt

```
Rules:
- ONLY use facts from the cited sources. Do NOT blend facts across sources.
- If two sources disagree, name both and pick the one with higher similarity score (or higher source_count for entities).
- Every fact in your answer MUST cite its source.
- If sources are insufficient: reply EXACTLY "I don't have enough in the knowledge graph to answer that confidently."
- Prefer structured prose over lists unless the answer is enumerable.
```

### Model auto-switch

`config.SYNTHESIS_MODEL_MAP`:

```python
SYNTHESIS_MODEL_MAP = {
    "rule":    "gpt-5.4-mini",   # legal/HR — precision matters
    "project": "gpt-5.4-mini",   # client-facing — precision matters
    # all others → default (Gemma4:e2b)
}
DEFAULT_SYNTHESIS_MODEL = MASTER_MODEL  # gemma4:e2b
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
```

If `OPENAI_API_KEY` empty → fallback to Gemma for all intents (warn in log).

### Re-chunking

`config.CHAT_CHUNK_CHARS = 500` (from 1200), `CHAT_CHUNK_OVERLAP = 80`. Wipe `document_chunks` table + Chroma chunks collection on first run post-deploy. Re-ingest docs.

---

## Telegram inbound + CEO edits

### Architecture

```
telegram long-poll loop (background thread/process)
   ↓
inbound msg → look up sender chat_id in live Persons
   ↓
   ├─ unknown sender → reply: "Not authorized. Ask the admin to register you."
   └─ known sender → identify role
        ↓
        msg → intent classifier
        ↓
        ├─ query intent → ORACLE → reply
        ├─ config_edit intent + CEO role → propose patch (with confirm/cancel buttons) → CEO confirms → apply + audit
        ├─ config_edit intent + non-CEO → queue in ReviewQueue → reply: "queued for CEO approval"
        └─ command (`/scan`, `/pending`, etc) → execute → reply
```

### Long-poll loop (no public URL needed)

```python
# capabilities/telegram_bot.py
def start_loop(stop_event):
    offset = 0
    while not stop_event.is_set():
        updates = telegram_get_updates(offset=offset, timeout=30)
        for u in updates:
            handle_message(u)
            offset = u["update_id"] + 1
```

Loop launched in a background thread when `TELEGRAM_BOT_TOKEN` set AND `--with-bot` flag passed to main.py (opt-in to avoid surprises).

### Slash commands

| Command | What |
|---------|------|
| `/scan` | DONNA scan_all, reply with digest |
| `/pending` | List pending entities count |
| `/me` | Show how the bot identifies you |
| `/register <chat_id> <email>` | (CEO only) link a chat_id to a Person |
| `/help` | List commands |

### config_edit intent → patch flow

LLM asked: "Generate JSON patch":

```json
{
  "section": "identity",
  "path": ["hq"],
  "action": "set",
  "from_value": null,
  "new_value": "Immeuble Mazars, 1 Rue du Lac Ghar el Melh, La Marsa Tunis"
}
```

CEO receives Telegram message with inline keyboard:
```
✏ Proposed: identity.hq = "Immeuble Mazars, 1 Rue du Lac..."
[Confirm]  [Cancel]
```

Confirm → apply via `yaml_io.write_yaml_atomic` + append to `_meta.edit_history`. Reply "✅ Applied."

---

## Build plan — sub-phases

### 9.0 — company-config initialization (~30 min)
- `scripts/init_company.py` — CLI prompts for identity (name, hq, industry, etc), leadership (CEO name + email, CTO, HR lead), tools, culture values. Writes clean `company-config.yml`. Backs up old one to `company-config.yml.bak`.
- Add `_meta.edit_history` plumbing in `capabilities/yaml_io.py` — helper `append_edit_history()`
- `yaml_sync.py` appends edit entry on each sync

### 9.1 — Data model (~3h)
- entity_types.py — `Client`, `Project.kind`, `Project.client_id`, `Team.kind`, `Team.external_org`, `Person.telegram_chat_id`
- graph_store.py — no schema change needed (entities are JSON blob); just update conflict + dedup helpers
- promotion.py — new gates for Client, updated Project/Team
- cartographer.py — extractor prompt mentions Clients, Project kind detection (client name → external)
- pending.py — Promote (Client) button, Project promotion asks for kind (internal/external) + client picker if external
- NEW `tui/screens/clients.py` — grid of clients (similar to Externals)
- teams.py — kind picker on create, external_org field
- edges.py — new types: OWNED_BY, WORKS_ON, BELONGS_TO_CLIENT
- yaml_sync.py — `_build_clients()`, projects emit `kind` + `client_id`, teams emit `kind` + `external_org`
- App: `c` key → Clients screen

### 9.2 — ORACLE rebuild (~4h)
- Split `agents/oracle.py` into:
  - `oracle.py` (top-level invoke)
  - `oracle_intent.py` (classifier)
  - `oracle_retrieve.py` (per-intent retrievers)
  - `oracle_synth.py` (synthesizer + model auto-switch)
- Add OpenAI client wrapper in `capabilities/llm.py` (Ollama + OpenAI under one interface)
- TUI Query screen: dynamic suggestion buttons after clarification reply
- Re-chunk: drop tables, re-ingest

### 9.3 — Telegram inbound + CEO edits (~3h)
- `capabilities/telegram_bot.py` — long-poll loop, handle_message, slash commands
- `capabilities/yaml_io.py` — `propose_patch()` + `apply_patch()` with edit_history
- Person.telegram_chat_id wired in entity_types, browser detail, pending classification
- `main.py --with-bot` flag → spawns background thread
- Inline keyboard helper for confirm/cancel
- CEO check: `Person.role.lower() in {"ceo", "founder", "admin"}` OR sub_roles contains those

### 9.4 — Quick UX wins (~30 min)
- Browser / Pending / Review: left column 40%, detail 60%
- Teams screen: redesign with vertical spacing + separate Add/Remove cards

---

## Open / deferred (not in Phase 9)

- Sub-projects (D5 deferred)
- Webhook Telegram (long-poll suffices)
- Multi-CEO / multi-admin RBAC (single CEO check OK for MVP)
- Translating Arabic text in extraction
- Bigger model for extraction (only synthesis switches; extraction stays Gemma for now — switch later if needed)

---

## Risk register

| Risk | Mitigation |
|------|------------|
| OpenAI rate limits / cost surprise | Cache responses by (intent + question hash), log spend, env-gate by `OPENAI_API_KEY` |
| Long-poll loop blocks shutdown | `stop_event` from main, daemon thread |
| CEO patch goes wrong | Always backup current yaml before apply, edit_history allows revert |
| LLM intent classifier hallucinates | Lexical fast-path covers obvious cases; LLM JSON validated against schema |
| Smaller chunks → too many results | Cap retrieval k=10, sort by similarity, drop below 0.5 cosine sim |
| Telegram impersonation | Only by Person.telegram_chat_id field. Initial bind requires CEO via `/register` |
