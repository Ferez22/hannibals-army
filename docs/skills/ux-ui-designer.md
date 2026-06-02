# Skill: TUI UX/UI Designer

> How to design and review Textual screens for Hannibal's Army. Used for every TUI change.

## When to use

- Adding a new screen
- A screen looks broken (wrong widths, overlapping widgets, buttons cut off)
- A button-action loses state (e.g., Select.value resets unexpectedly)
- Designing a flow that touches multiple screens

## Principles

### 1. Always declare explicit widths on Horizontal children

Textual's default is content-based. With empty `Static` widgets, they take 0 width and the rest hogs everything.

**Bad:**
```python
with Horizontal():
    yield DataTable()
    yield Static("", id="detail")
```
→ DataTable takes everything, Static is invisible.

**Good:**
```python
with Horizontal(classes="split-pane"):
    with VerticalScroll(classes="split-pane-left"):
        yield DataTable()
    with VerticalScroll(classes="split-pane-right"):
        yield Static("", id="detail")
```
With CSS:
```css
.split-pane-left, .split-pane-right { width: 1fr; height: 1fr; overflow-y: auto; }
```

### 2. Width math: `width: 50%` inside a 50%-width column = 25% of screen

This bit us in Pending (action buttons appeared cropped). When a row is nested in an already-constrained column, use `width: 1fr` (full of parent), not percentages.

### 3. VerticalScroll prevents overflow

If a screen can grow beyond terminal height, wrap content in `VerticalScroll`. Plain `Vertical` clips.

### 4. Buttons placement

- **Top of column** for primary actions (Pending: Promote/Reject buttons at top)
- **Bottom of form** for submit (Edges screen: "Create edge" at bottom of form)
- **Inline** with the row they act on (Teams: Add/Remove member near their inputs)

### 5. Short button labels

Terminal is narrow. `Promote (Employee)` is 18 chars and 4 of them barely fit a row. Prefer `→ Employee`, `Verify`, `Replace`, `Delete`.

### 6. Color semantics (per `config.PALETTE`)

| Hex | Name | Use |
|-----|------|-----|
| `#5BC8F5` | primary (lightblue) | Headers, agent names, neutral emphasis |
| `#FFFFFF` | text (white) | Body text |
| `#F5A623` | highlight (orange) | Attention, in-progress, selection |
| `#F5D020` | accent (yellow) | Metadata, money-touching (clients), warnings |
| `#E74C3C` | danger (red) | Destructive, stale, conflicts, errors |
| `#2ECC71` | success (light green) | Confirmed, verified, success states |
| `#4A5568` | dim (gray) | Borders, inactive, secondary text |
| `#0D1117` | bg (near-black) | Background |

Be consistent: red = "this could break things". Yellow = "needs your attention". Green = "good outcome confirmed".

### 7. The Select preservation pattern

When refreshing a Select's options, its `.value` resets to BLANK. This loses user selection silently.

**The pattern (see `tui/screens/teams.py:_set_options_preserve`):**

```python
def _set_options_preserve(self, selector: str, opts: list[tuple[str, str]]) -> None:
    sel = self.query_one(selector, Select)
    prev = sel.value
    sel.set_options(opts)
    if prev is not None and prev != Select.BLANK and any(v == prev for _, v in opts):
        try:
            sel.value = prev
        except Exception:
            pass
```

**ALWAYS use this pattern when refreshing Selects.**

### 8. Never call full refresh on row-hover events

`DataTable.RowHighlighted` fires on cursor moves AND focus changes. If your handler does `refresh_all()`, you'll reset Selects, banners, and form inputs every time the user clicks anything.

**The pattern (see `tui/screens/teams.py:_update_for_selected_team`):**

Track last selected ID. Skip rebuild when selection unchanged.

```python
def on_row(self, event: DataTable.RowHighlighted) -> None:
    self._update_for_selected_team()  # internally: skip if team_id unchanged
```

### 9. Banner / action-feedback widget

Don't write success/error messages into the same widget that other events update. Dedicated banner widget at top of screen:

```python
yield Static("", id="screen-banner")
```

Only action handlers write to it. RowHighlighted doesn't touch it.

### 10. Buttons that have side effects need confirmation

Two-click confirm pattern (see `tui/screens/browser.py:delete_node`):

```python
if getattr(self, "_delete_confirmed", None) != node["id"]:
    self._delete_confirmed = node["id"]
    banner.update(f"⚠ Delete '{name}'? Click Delete again to confirm.")
    return
# else: actually delete
```

Use for: delete, force-promote, external-add-to-internal-team.

### 11. Screen vs Modal

Screens for major navigation (Browser, Pending, Review).
Modals (`ModalScreen`) for transient confirms — but we mostly avoid them; inline two-click is simpler.

### 12. Friendly detail over JSON dump

When showing a single entity's fields, format them with labels and color, not `json.dumps`. See `tui/screens/pending.py:_friendly_detail`.

```
▌ John Smith
Person  ·  person_abc123
  kind: employee
  emails: john@x.com
  role: Engineering Lead
```

JSON is for debug. Friendly view is for users.

## Layout cheat sheet

| Need | Use |
|------|-----|
| Side-by-side panes | `Horizontal` with `width: 1fr` on each child + `VerticalScroll` for content |
| Full-height scrollable | `VerticalScroll` as content container |
| Form rows | `Horizontal` with `height: auto`, children with `width: 1fr` or fixed widths |
| Card grid | `Grid` with `grid-size: 2` and `grid-gutter: 1 2` |
| Fixed-height buttons | `height: 3` on Button |
| Action toolbar | `Horizontal` with `height: 3` at top of column |

## Test pass checklist for any screen

- [ ] Renders correctly at 80x24, 120x40, fullscreen
- [ ] All interactive widgets reachable via keyboard (Tab order makes sense)
- [ ] Esc returns to previous screen (handled by app-level)
- [ ] Action feedback visible (banner) and persistent
- [ ] No banner-flash bug (action message survives subsequent focus events)
- [ ] Selects preserve value across refreshes
- [ ] DataTable cursor preserved across refreshes (track last selected ID)
- [ ] Empty state has a friendly message, not blank
- [ ] Destructive actions require two-click confirm
- [ ] No JSON dumps for normal users — friendly views only

## Common bugs and their fixes

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Select shows but value doesn't stick | `set_options` reset value | Use `_set_options_preserve` pattern |
| Button cropped off screen | Width inside nested column | `width: 1fr`, not `50%` |
| Right pane invisible | No CSS width on Static | Add `width: 1fr` and content |
| Screen too tall, content cut | Plain Vertical container | Switch to `VerticalScroll` |
| Banner flashes then disappears | RowHighlighted triggers refresh that overwrites banner | Refactor refresh to not touch banner |
| Cursor jumps to row 0 on refresh | `table.clear()` resets cursor | Capture last ID, call `table.move_cursor(row=idx)` after rebuild |
| Esc on Home screen turns black | `pop_screen` removes Home, leaves nothing | Guard `action_back` to skip if current is HomeScreen |
