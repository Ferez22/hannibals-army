# Phase 10 — Tier-Gated Manager Copilot + Google Workspace

> Revised north star (2026-06-06): tool serves CEO + C-Level + Directors + Managers + Everyone in a pyramid permission model. Google Workspace (Drive, Gmail extracts, Calendar) is the canonical source of truth. Single tenant (QartMina). Local-first KG; cloud synth allowed.

## Tier model

```
TIER 0  ceo          sees everything
TIER 1  c_level      sees c_level + below
TIER 2  director     sees director + below
TIER 3  manager      sees manager + below
TIER 4  everyone     baseline org info only
```

- **Ownership beats tier.** Owner of a project/document always sees their own asset regardless of tier.
- **Tier rank is integer**, computed at query time from the enum label. Storage uses the label string.
- **Adding tiers later** (HR/Legal horizontal, Board above CEO) = append to enum + remap rank function.
- **Unknown sender** = TIER 4 (everyone) baseline. Refuse content queries until `/register` resolves identity.

## New entities + fields

### Person
```python
tier: Literal["ceo", "c_level", "director", "manager", "everyone"] = "everyone"
tier_confirmed: bool = False    # CEO confirmed in Pending
```

### Document
```python
tier: Literal[...] = "director"             # SENTINEL default-conservative
tier_reason: str | None = None              # SENTINEL explanation
tier_confirmed_by: str | None = None        # admin person_id
tier_confirmed_at: datetime | None = None
doc_kind: Literal["contract", "private", "general", "presentation", "report", "policy"] | None = None
owner_id: str | None = None                 # Person who owns this doc
```

### Project / Team
- Add `tier` (defaults from owner's tier, override allowed).
- `owner_id` already implicit via `lead_id`; explicit `owner_id` field for clarity.

### Meeting (new, calendar-fed)
- Org-wide visibility (no tier field).
- Fields: `title, start, end, attendees: list[str], source: Literal["gcal"], external_id: str`.

## New agent — SENTINEL

| Stage | Job |
|-------|-----|
| Post-extraction | Classify `doc_kind` (LLM prompt: contract/private/general/presentation/report/policy) |
| Tier deduction | Apply `doc_kind → tier` rules + content signals (NDA, salary, board → c_level) |
| Stage | Tier attached to staged document; admin confirms in Pending |
| Confidence gate | Low confidence forces manual review |

**Files:** `agents/sentinel.py` + `capabilities/tier_classify.py` (pure rules + one LLM call).

### Default tier rules

| doc_kind | Signal hits | Default tier |
|----------|-------------|--------------|
| contract | client name only | director |
| contract | board/shareholders | c_level |
| private | salary, comp, performance | c_level |
| private | HR investigation | c_level |
| presentation | "all-hands", "company-wide" | everyone |
| presentation | "board", "exec" | c_level |
| report | financial statements | c_level |
| report | dept ops, weekly review | director |
| policy | handbook, code of conduct | everyone |
| general | (default) | director |

## Pipeline change

```
BEFORE: RAGNAR → CARTOGRAPHER → staging → admin → live KG
AFTER : RAGNAR → CARTOGRAPHER → SENTINEL → staging (with tier) → admin confirms entity+tier → live KG
```

SENTINEL adds ~1 LLM call per doc. Acceptable cost.

## ORACLE tier filter

Sender Telegram chat_id → Person → `tier` → `sender_tier_rank`. Pass through to every retriever.

```python
# in oracle_retrieve._chunk_search
where = {
    "$or": [
        {"tier_rank": {"$lte": sender_tier_rank}},
        {"owner_id": sender_person_id},
    ]
}
```

SQLite: `WHERE tier_rank <= ? OR owner_id = ?`.

Unknown / pre-registration sender → `everyone` tier, content queries refused with `/register` prompt.

## Google Workspace integration

### Surfaces

| Surface | Strategy | Privacy |
|---------|----------|---------|
| Directory | Pull org chart → bootstrap Person tier hierarchy from role titles | Public org data |
| Drive | OAuth per manager, sync files → `RawDocument` → existing ingest pipeline; folder→tier hints to SENTINEL | Per-user OAuth |
| Gmail | OAuth per manager, raw mail STAYS SANDBOXED. Only LLM-extracted facts (decisions, commitments) enter KG with sender manager's tier as ceiling. | Per-user, extract-only |
| Calendar | OAuth per manager, meetings + attendees → Meeting entity + edges. **Org-wide visibility** (exempt from tier). | Per-user OAuth, shared visibility |

### Auth flow

1. Manager sends `/register` to Telegram bot.
2. CEO sees pending registration in TUI banner / Telegram DM.
3. CEO approves in TUI (whitelist).
4. Manager binds Google account via OAuth flow (browser, one-time).
5. Refresh token stored encrypted in SQLite per Person.

## Phase sequence

| Sub-phase | Name | Estimate | Output |
|-----------|------|---------:|--------|
| **10A** | Tier foundations — Person.tier, Document.tier, enum, ORACLE filter, sender resolution | ~3h | Tier-gated answers, manual tier assignment in Pending |
| **10B** | SENTINEL agent — doc_kind classifier + tier rules + Pending confirm UI | ~3h | Auto-tiering of docs with admin confirmation |
| **10C** | Ownership-override — owner_id on Project/Document, retrieval `OR` clause | ~1.5h | Owner sees own assets across tiers |
| **11A** | GWS Directory — pull org chart, auto-bootstrap Person + hierarchy | ~3h | Real org chart, no manual Person creation |
| **11B** | GWS Drive — OAuth, incremental sync, folder→tier hints | ~4h | Drive files in KG |
| **11C** | GWS Gmail (extract-only) — OAuth, sandbox raw, facts to KG | ~4h | Decisions/commitments captured from email |
| **11D** | GWS Calendar — Meeting entity, attendee edges, org-wide visibility | ~2h | Who-works-with-whom signal |
| **12** | Conversation memory — per-Person multi-turn chat | ~2h | Bot remembers prior turns per user |
| **13** | Learning loop — 👍/👎, persona memory, Q&A as KG nodes | ~3-4h | Bot sharpens per manager |
| **14** | Tasks entity — TUI/Telegram CRUD | ~2h | Productivity surface |
| **15+** | Integrations — Notion, Slack, Google Tasks | ~3h each | Pull from work surfaces |

Total to Phase 14 ship: ~30–35h.

## New design decisions

18. **Tier is rank-comparable** — lower rank = more access. Storage uses label string; rank computed via `TIER_RANKS` map in `config.py`. Adding tier = append + remap.
19. **Default tier on ambiguous docs = `director`** — conservative. Over-restrict beats leak.
20. **Sender resolution failure = `everyone` + refuse content** — `/register` mandatory before content access.
21. **SENTINEL runs at ingest, not retrieval** — tier baked into stored metadata. Re-classify only on manual re-ingest.
22. **Gmail raw never in KG** — only structured extractions. Raw stays per-user sandbox or discarded.
23. **Calendar = org-wide** — exempt from tier model. Meetings always visible.
24. **GWS-sourced nodes carry `source_owner_id`** — drives ownership-override rule for retrieval.
25. **Tier confirmation gates ORACLE visibility** — until `tier_confirmed=True`, doc only visible to CEO + owner.

## Risk register

| Risk | Mitigation |
|------|------------|
| SENTINEL mis-tiers sensitive doc → leak | Default-conservative (`director`); `tier_confirmed` gate blocks ORACLE until admin confirms |
| Manager Telegram chat hijack → tier escalation | `/register` requires CEO whitelist; chat_id rotation audit; periodic re-confirm |
| GWS OAuth scaling | Start with CEO + 2-3 directors; grow whitelist incrementally |
| Gmail extraction over-shares facts | Each fact inherits sender manager's tier as ceiling; SENTINEL sees email subject + sender tier hint |
| Owner-override leaks via citation | Higher-tier user querying chunk owned by lower-tier user — chunk filtered by sender's tier, not owner's. Owner-override applies only to retrieval for owner themselves. |
| Tier renumbering breaks data | Tier stored as string label; rank computed at query time |

## Open questions

1. **Person.tier source** — auto from GWS Directory role title parsing? Manual CEO assignment? Both with auto as suggestion?
2. **Pending screen** — same screen with new "Confirm tier" action, or separate Tier Review screen?
3. **`/register` notification** — Telegram DM to CEO chat? TUI banner? Both?
4. **OAuth token storage** — SQLite blob encrypted at rest (Fernet via app key)? Or `.env` for CEO-only?
5. **Re-ingest semantics** — if doc tier changes, what about existing chunks in Chroma? Wipe+re-embed, or in-place metadata update?
