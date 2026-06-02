# Skill: Agentic Tester

> Standardized validation pass for each phase. Catch regressions before they reach the user.

## When to use

- After completing any phase
- After touching extractor, dedup, promotion, or ORACLE
- Before a commit that changes user-visible behavior
- When debugging "the bot is acting weird"

## Test levels

### Level 0 — Import smoke (10 seconds)

```bash
.venv/bin/python -c "from tui.app import HannibalsArmyApp; print('imports OK')"
```

Catches: missing import, typo in class name, broken Pydantic model.

### Level 1 — Logic unit test (2 minutes)

For each component touched, test with synthetic data:

```bash
.venv/bin/python -c "
from agents.donna import detect_conflict
# test conflict path
live = {'fields': {'kind': 'internal'}}
cand = {'kind': 'external', 'external_org': 'X'}
print(detect_conflict('Team', cand, live))
"
```

Catches: branch bugs, off-by-one, wrong field name.

### Level 2 — Extraction spike (3 minutes)

```bash
.venv/bin/python scripts/extraction_spike.py
```

Catches: prompt regression, JSON validity drop, entity recall drop.

Acceptance gates (from `docs/EXTRACTION_BASELINE.md`):
- JSON validity ≥ 80%
- Person precision ≥ 70%
- Person recall ≥ 60%

### Level 3 — End-to-end TUI walkthrough (5 minutes)

Full pass after any visible change:

1. `rm -rf db/graph.db memory/chroma` (clean slate)
2. `.venv/bin/python main.py`
3. Visit every screen with relevant changes
4. Ingest at least 2 sample docs
5. Walk the canonical sequence (see below)

### Level 4 — Telegram smoke (when Telegram code touched)

1. `.venv/bin/python -c "from capabilities.notifier import send_telegram; send_telegram('test')"`
2. Verify message lands in your Telegram chat
3. Restart TUI — does auto-scan fire if `scan_log` is old?

## Canonical test sequence (after any phase)

### Setup
```bash
rm -rf db/graph.db memory/chroma
.venv/bin/python main.py
```

### Step 1 — Home screen baseline
- ✅ All entity counts at 0
- ✅ Status bar reads `● READY    pending: 0    conflicts: 0`
- ✅ 5 agents listed
- ✅ All key shortcuts shown

### Step 2 — Ingest paths
For each of: `Handbook (1).docx`, `Procuration_sonia-hassas.pdf`, `MITRA (1).xlsx`, `Accord de consultation OpenAI.pdf`:
- Ingest via `i` screen
- ✅ Result card shows: doc title, summary, promoted/staged counts
- ✅ Compact log entry below
- ✅ No exception

### Step 3 — Pending triage
- ✅ Pending list shows rows for each staged entity
- ✅ Friendly detail (NOT JSON) on row select
- ✅ All 4 buttons visible (Employee/External/Other/Reject)
- ✅ Promote (Employee) on a Person → moves to live
- ✅ Promote (External) → asks for company, completes
- ✅ Promote (other) on a Client → moves to live

### Step 4 — Manual entity creation
- ✅ Teams screen: create internal team
- ✅ Teams screen: create external team with external_org
- ✅ Teams screen: try external without external_org → red error
- ✅ Edges screen: create MEMBER_OF, WORKS_ON, OWNED_BY edges
- ✅ External → internal team requires confirmation click

### Step 5 — Read-back validation
- ✅ Browser → cycle through every entity type with ←/→
- ✅ Each tab shows correct count
- ✅ Stale indicator behavior (test with `scripts/age_nodes.py` if needed)
- ✅ Employees grid shows only kind=employee
- ✅ Externals grid shows only kind=external
- ✅ Clients grid shows clients with linked projects
- ✅ Teams screen shows members with role/sub_roles

### Step 6 — ORACLE queries
Run these in Query screen, note pass/fail:

| Query | Expected behavior |
|-------|-------------------|
| `who is the CEO?` | Entity hit on Person, cites person_xxx |
| `who works on additionality` | Hits Project → traverses to people (Phase 9.2+) |
| `what does the handbook say about X` | Cites doc chunk |
| `tell me about the company` | Summary mode, lists all entities |
| `what are our clients` | Lists Client nodes |
| `vague: what's important right now` | (Phase 9.2+) clarification with suggestion buttons |

### Step 7 — System integrity
- ✅ `company-config.yml` — sections present and populated, `_meta.edit_history` has entries
- ✅ `db/graph.db` — `sqlite3 db/graph.db "SELECT entity_type, COUNT(*) FROM live_nodes GROUP BY entity_type;"`
- ✅ `memory/chroma/` — exists and grew after ingestion
- ✅ `logs/army.log` — no `ERROR` or `Exception` lines

### Step 8 — DONNA
- ✅ Press `s` on Review screen → "nothing stale right now" if data is fresh
- ✅ Aged data → review queue populates, Telegram digest fires
- ✅ Verify action on a stale row → row disappears, badge clears in Browser

## When the test fails

Don't ship. Find the root cause.

### Diagnostic order
1. **Tail logs:** `tail -f logs/army.log` — look for the exception
2. **Inspect DB:** `sqlite3 db/graph.db ".tables"`, then `SELECT * FROM live_nodes ORDER BY created_at DESC LIMIT 5;`
3. **Inspect review queue:** `SELECT * FROM review_queue WHERE resolved=0;`
4. **Inspect raw extraction:** Check `data/samples/_extracted_*.json` from the spike, or add `log.info("raw", extra={...})` to extractor temporarily
5. **Replicate in isolation:** Run the failing step via `python -c "..."` outside the TUI
6. **Check edit_history:** `python -c "import yaml; print(yaml.safe_load(open('company-config.yml'))['_meta']['edit_history'][-5:])"`

### Common failure modes

| Symptom | Check |
|---------|-------|
| Ingest succeeds but entity not in Browser | yaml_sync vs CARTOGRAPHER write order; check live_nodes table |
| Edge created but doesn't show in detail | Field-edge sync (Phase 9.1 pattern); use `kg.graph.edges_from/edges_to` |
| ORACLE says "I don't know" but data exists | Vector search returning 0 hits; check chunk_count + node embedding |
| Stale badge stays after Verify | last_verified_at not updated; check Browser refresh on screen_resume |
| Pending count off from reality | promotion_status='pending' filter; some staged with other status |
| Telegram silent | `notifier.telegram_configured()` returns false → check .env loaded |

## Documenting test results

Per phase, write findings to `docs/PHASE_X_VALIDATION.md`:

```
## Phase 9.1 — Clients + Project kind

### Date: 2026-06-01

### Test pass: ✅ / ❌ / 🟡

### Findings
- ✅ Teams kind picker works, validates external_org
- ✅ Client entity stages correctly with `awaiting_validation`
- 🟡 Edges OWNED_BY not syncing Project.client_id (FIXED in commit XYZ)
- ❌ ORACLE doesn't use edges yet — deferred to Phase 9.2
```

Keep these as regression baselines.
