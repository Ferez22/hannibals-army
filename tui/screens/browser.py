"""Browser screen — list live entities, view detail + edges."""
from __future__ import annotations

import json

from datetime import datetime

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static

import config
from agents.donna import is_stale
from core.ingestion_pipeline import get_kg

ENTITY_TYPES = ["Person", "Team", "Project", "Client", "Rule", "Event", "Document"]


def _resolve_person_label(person_id: str | None) -> str:
    """Render `Name (id)` for a Person id; '—' when unset; raw id when unresolved."""
    if not person_id:
        return "—"
    node = get_kg().get_live(person_id)
    if not node:
        return f"{person_id} [dim](unresolved)[/]"
    return f"{node['fields'].get('name', '?')}  [dim]{person_id}[/]"


class BrowserScreen(Screen):
    BINDINGS = [
        ("left",  "prev_type", "Prev type"),
        ("right", "next_type", "Next type"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.current_type_idx = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="b-title", classes="section-title")
        yield Static("", id="b-banner")
        with Horizontal(classes="split-pane"):
            with VerticalScroll(classes="split-pane-left"):
                with Horizontal(id="b-actions"):
                    yield Button("Delete", variant="error", id="b-delete")
                yield DataTable(id="b-table", zebra_stripes=True)
            with VerticalScroll(classes="split-pane-right"):
                yield Static("[dim]select a row[/]", id="b-detail")
                with Horizontal(id="b-tier-row"):
                    yield Static("[#F5A623]Tier:[/]", id="b-tier-label")
                    yield Select(
                        options=[(t, t) for t in config.TIERS],
                        id="b-tier",
                        prompt="tier",
                        value=config.DEFAULT_DOC_TIER,
                        allow_blank=False,
                    )
                    yield Button("Confirm tier", variant="success", id="b-confirm-tier")
                # Lazy reason input — shown only when CEO disagrees with SENTINEL.
                yield Input(
                    placeholder="why? (1 sentence) — press Enter to apply",
                    id="b-tier-reason",
                    classes="hidden",
                )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#b-table", DataTable)
        table.add_columns("id", "name", "confidence")
        table.cursor_type = "row"
        self.refresh_type()

    def on_screen_resume(self) -> None:
        # Re-read graph state when returning from Review/Pending
        self.refresh_type()

    def action_prev_type(self) -> None:
        self.current_type_idx = (self.current_type_idx - 1) % len(ENTITY_TYPES)
        self.refresh_type()

    def action_next_type(self) -> None:
        self.current_type_idx = (self.current_type_idx + 1) % len(ENTITY_TYPES)
        self.refresh_type()

    def refresh_type(self) -> None:
        et = ENTITY_TYPES[self.current_type_idx]
        self.query_one("#b-title", Static).update(
            f"[bold #F5A623]{et}[/]  [dim]←/→ change type[/]"
        )
        kg = get_kg()
        nodes = kg.list_live(et)
        table = self.query_one("#b-table", DataTable)
        table.clear()
        for n in nodes:
            name = n["fields"].get("name") or n["fields"].get("title") or "—"
            conf = n["confidence"]
            color = "#2ECC71" if conf >= 0.6 else ("#F5A623" if conf >= 0.3 else "#E74C3C")
            name_cell = Text(str(name))
            if not n.get("confirmed", False):
                name_cell.append("  ⚠unconfirmed", style="bold #F5D020")
            if is_stale(n):
                name_cell.append("  ●stale", style="bold #E74C3C")
            conf_cell = Text(f"{conf:.2f}", style=color)
            table.add_row(n["id"][:24], name_cell, conf_cell)
        self.query_one("#b-detail", Static).update("[dim]select a row to inspect[/]")

    def _current_node(self) -> dict | None:
        table = self.query_one("#b-table", DataTable)
        if table.cursor_row is None or table.cursor_row < 0:
            return None
        et = ENTITY_TYPES[self.current_type_idx]
        nodes = get_kg().list_live(et)
        if not nodes or table.cursor_row >= len(nodes):
            return None
        return nodes[table.cursor_row]

    @on(Button.Pressed, "#b-confirm-tier")
    def confirm_tier(self) -> None:
        node = self._current_node()
        banner = self.query_one("#b-banner", Static)
        if not node:
            banner.update("[red]no row selected[/]")
            return
        if node["entity_type"] != "Document":
            banner.update("[red]Confirm tier only for Document rows[/]")
            return
        tier_sel = self.query_one("#b-tier", Select).value
        if not isinstance(tier_sel, str) or tier_sel not in config.TIERS:
            banner.update("[red]pick a tier first[/]")
            return
        sentinel_tier = node["fields"].get("tier")
        # Disagreement → prompt for reason
        if sentinel_tier and tier_sel != sentinel_tier:
            self._pending_override = (node["id"], tier_sel)
            reason_input = self.query_one("#b-tier-reason", Input)
            reason_input.remove_class("hidden")
            reason_input.value = ""
            reason_input.focus()
            banner.update(
                f"[#F5D020]Override:[/] SENTINEL → {sentinel_tier}, you → {tier_sel}. "
                "Type one-line reason and press Enter."
            )
            return
        # Silent agreement
        self._apply_tier_confirmation(node, tier_sel, ceo_reason=None)

    @on(Input.Submitted, "#b-tier-reason")
    def submit_tier_reason(self, event: Input.Submitted) -> None:
        reason = event.value.strip()
        pending = getattr(self, "_pending_override", None)
        if not pending:
            return
        node_id, tier_sel = pending
        nodes = get_kg().list_live("Document")
        node = next((n for n in nodes if n["id"] == node_id), None)
        if not node:
            self.query_one("#b-banner", Static).update("[red]row no longer exists[/]")
            self._pending_override = None
            return
        if not reason:
            self.query_one("#b-banner", Static).update(
                "[red]reason required when overriding SENTINEL — type something[/]"
            )
            return
        self._apply_tier_confirmation(node, tier_sel, ceo_reason=reason)
        self._pending_override = None
        ri = self.query_one("#b-tier-reason", Input)
        ri.add_class("hidden")
        ri.value = ""

    def _apply_tier_confirmation(
        self, node: dict, tier_sel: str, *, ceo_reason: str | None,
    ) -> None:
        from capabilities import tier_memory

        kg = get_kg()
        now = datetime.now().isoformat()
        admin = config.TELEGRAM_ADMIN_CHAT_ID or "tui-admin"
        kg.update_live_field(node["id"], "tier", tier_sel)
        kg.update_live_field(node["id"], "tier_confirmed_by", admin)
        kg.update_live_field(node["id"], "tier_confirmed_at", now)

        # Record into tier_corrections for SENTINEL learning loop
        f = node["fields"]
        sentinel_snapshot = {
            "doc_kind": f.get("doc_kind"),
            "tier": f.get("tier") if not ceo_reason else None,  # NB: tier was already overwritten above
            "reason": f.get("tier_reason"),
            "source": None,
        }
        # Re-fetch original SENTINEL tier from the in-memory copy (node was captured before update)
        original_sentinel_tier = node["fields"].get("tier")
        sentinel_snapshot["tier"] = original_sentinel_tier
        # doc_text source: we don't have raw text on hand; use title + summary as proxy
        proxy_text = f.get("summary") or f.get("title") or ""
        try:
            tier_memory.record_correction(
                kg=kg,
                doc_id=node["id"],
                doc_title=f.get("title", ""),
                doc_text=proxy_text,
                sentinel=sentinel_snapshot,
                ceo_kind=f.get("doc_kind"),
                ceo_tier=tier_sel,
                ceo_reason=ceo_reason,
                override_by=admin,
            )
        except Exception as e:
            # Never break tier confirm because of memory write
            self.query_one("#b-banner", Static).update(
                f"[#F5D020]tier set, memory write failed:[/] {e}"
            )
        else:
            badge = "[#F5D020]override[/]" if ceo_reason else "[#2ECC71]confirmed[/]"
            self.query_one("#b-banner", Static).update(
                f"{badge} {tier_sel} on {node['id']}"
            )
        self.refresh_type()

    @on(Button.Pressed, "#b-delete")
    def delete_node(self) -> None:
        node = self._current_node()
        banner = self.query_one("#b-banner", Static)
        if not node:
            banner.update("[red]no row selected[/]")
            return
        # Two-click confirmation
        confirm_key = node["id"]
        if getattr(self, "_delete_confirmed", None) != confirm_key:
            self._delete_confirmed = confirm_key
            name = node["fields"].get("name") or node["fields"].get("title") or node["id"]
            banner.update(
                f"[bold #F5D020]⚠ Delete {node['entity_type']} '{name}'?[/]  "
                f"This removes the node + all its edges. Click [bold]Delete node[/] again to confirm."
            )
            return
        self._delete_confirmed = None
        result = get_kg().delete_node(node["id"])
        banner.update(
            f"[#E74C3C]deleted[/] {node['id']}  "
            f"(edges removed: {result['edges_removed']})"
        )
        self.refresh_type()

    @on(DataTable.RowHighlighted)
    def on_row(self, event: DataTable.RowHighlighted) -> None:
        # Reset delete confirmation when cursor moves
        self._delete_confirmed = None
        if event.cursor_row is None or event.cursor_row < 0:
            return
        et = ENTITY_TYPES[self.current_type_idx]
        nodes = get_kg().list_live(et)
        if not nodes or event.cursor_row >= len(nodes):
            self.query_one("#b-detail", Static).update("[dim]no rows[/]")
            return
        node = nodes[event.cursor_row]
        # Sync tier picker with node's current tier (Document only)
        if et == "Document":
            current_tier = node["fields"].get("tier") or config.DEFAULT_DOC_TIER
            try:
                tier_sel = self.query_one("#b-tier", Select)
                if current_tier in config.TIERS:
                    tier_sel.value = current_tier
            except Exception:
                pass
        confirmed_badge = (
            f"[#2ECC71]confirmed[/] by {node.get('confirmed_by') or '?'} @ {node.get('confirmed_at') or '?'}"
            if node.get("confirmed")
            else "[#F5D020]unconfirmed[/] (auto-promoted — review in Audit screen)"
        )
        lines = [
            f"[bold #5BC8F5]{node['id']}[/]",
            f"[dim]type:[/] {node['entity_type']}",
            f"[dim]confidence:[/] {node['confidence']:.2f}",
            f"[dim]source_count:[/] {node['source_count']}",
            f"[dim]created:[/] {node['created_at']}",
            f"[dim]last_verified:[/] {node['last_verified_at']}",
            f"[dim]review:[/] {confirmed_badge}",
        ]
        if et == "Document":
            f = node["fields"]
            tier = f.get("tier") or "—"
            confirmed_by = f.get("tier_confirmed_by")
            confirmed_at = f.get("tier_confirmed_at")
            kind = f.get("doc_kind") or "—"
            reason = f.get("tier_reason") or "—"
            badge = (f"[#2ECC71]confirmed[/] by {confirmed_by} @ {confirmed_at}"
                     if confirmed_by else "[#F5D020]unconfirmed[/]")
            owner_label = _resolve_person_label(f.get("owner_id"))
            lines.extend([
                "",
                f"[bold #F5A623]SENTINEL[/]  kind=[bold]{kind}[/]  tier=[bold]{tier}[/]  {badge}",
                f"[dim]reason:[/] {reason}",
                f"[#F5A623]owner:[/] {owner_label}  [dim](ownership beats tier)[/]",
            ])
        elif et == "Project":
            f = node["fields"]
            owner_label = _resolve_person_label(f.get("owner_id"))
            lines.extend([
                "",
                f"[#F5A623]owner:[/] {owner_label}  [dim](ownership beats tier)[/]",
            ])
        lines.extend([
            "",
            "[bold #F5A623]fields[/]",
            json.dumps(node["fields"], indent=2, ensure_ascii=False),
        ])
        # edges
        edges = get_kg().neighbors(node["id"])
        if edges:
            lines.append("")
            lines.append("[bold #F5A623]edges[/]")
            for e in edges:
                direction = "→" if e["from_id"] == node["id"] else "←"
                other = e["to_id"] if e["from_id"] == node["id"] else e["from_id"]
                role = f" ({e['properties'].get('role')})" if e["properties"].get("role") else ""
                lines.append(f"  {direction} {e['type']}{role}  {other}")
        self.query_one("#b-detail", Static).update("\n".join(lines))
