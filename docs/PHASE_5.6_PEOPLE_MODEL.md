# Phase 5.6 — People Model Refactor

> Distinguishes employees from externals, supports multi-email + sub-roles,
> adds teams CRUD and explicit kind classification.

---

## Data model changes

### Person

```python
class Person:
    id: str
    company_id: str
    name: str
    kind: Literal["employee", "external", "unknown"] = "unknown"   # NEW
    emails: list[str]                  # CHANGED — was single str
    contact: str | None
    role: str | None                   # primary role
    sub_roles: list[str]               # NEW
    tenure_since: str | None
    expertise: list[str]
    photo_path: str | None
    external_company: str | None       # NEW — only if kind=external
```

### Edge: MEMBER_OF properties

```
role: str
sub_roles: list[str]                   # NEW
tasks: list[str]
since: str | None
active: bool
```

---

## Promotion gates

| Entity | Condition | Auto-promote? |
|--------|-----------|---------------|
| Person | `kind == "unknown"` | ❌ Pending (reason: `needs_categorization`) |
| Person | `kind == "employee"` AND any email | ✅ |
| Person | `kind == "external"` AND `external_company` set | ✅ |
| All others | unchanged | unchanged |

Default: extractor produces `kind="unknown"` always. User classifies in Pending.

---

## Conflict resolution

| Field changed | Behavior |
|---------------|----------|
| `role` differs | Queue Review item kind=`role_conflict`, 3 actions: **Add as sub-role** / **Replace primary** / **Dismiss** |
| `emails` candidate has new email | Auto-append to live, no conflict |
| `kind` differs | Queue conflict (identity-level) |
| `name` differs | Queue conflict (already supported) |
| `external_company` differs | Queue conflict |

---

## Screens

### New

- **`TeamsScreen` (key `t`)** — list teams, create, edit, add/remove members. Hard external warning before adding non-employee.
- **`ExternalsScreen` (key `x`)** — grid of externals (different style from Employees).

### Changed

- **`EmployeesScreen`** — filter `kind == "employee"` only. Fix project traversal: 2-hop `Person → Team → Project` via `MEMBER_OF`+`RUNS`.
- **`PendingScreen`** — Person rows get two promote buttons: **Promote as Employee** / **Promote as External**. External path asks for `external_company` in modal.
- **`EdgesScreen`** — for MEMBER_OF type: separate `role` and `sub_roles` inputs. If picked Person is external + Team is internal → confirmation prompt.
- **`ReviewScreen`** — for `role_conflict`: 3 action buttons (Add as sub-role / Replace / Dismiss).
- **`BrowserScreen`** — Person detail shows kind badge + sub_roles list.

---

## Migration

**Wipe + reingest.** Decided per Q4. Document for user:

```bash
rm -rf db/graph.db memory/chroma data/photos
```

Then reingest. Photos lost (re-attach). Manual classifications lost (re-classify).

**Future note:** schema should be more stable post-5.6. Adopt alembic when next breaking change comes.

---

## YAML sync

`_build_people` rewrite. Now emits:
- `kind`
- `emails` array
- `sub_roles`
- `external_company`
- `memberships[].sub_roles` array

---

## Build order

1. `entity_types.py` — Person fields
2. `dedup.py` — emails array handling
3. `promotion.py` — kind=unknown blocks
4. `cartographer.py` — emit unknown kind, emails array, role_conflict queuing
5. `donna.py` — role-conflict path
6. `pending.py` — split Promote buttons (Employee/External)
7. `employees.py` — kind filter + 2-hop project traversal
8. `externals.py` — NEW
9. `teams.py` — NEW
10. `edges.py` — sub_roles input + external warning
11. `review.py` — role_conflict action buttons
12. `yaml_sync.py` — updated fields
13. `theme.py` — externals card styling, teams form
14. `app.py` + `home.py` — wire `t`, `x`

---

## Out of scope (future)

- `Organization` entity for external companies (text field for now)
- Bulk classification (CSV import of employee list)
- Team hierarchy depth limit
- "Embedded contractor" as third Person.kind (use external + confirmation flow for now)
