"""Audit screen — formerly Pending. Lists auto-promoted live nodes that
haven't been admin-confirmed yet (Phase 10D).

ORACLE flags answers that cite unconfirmed nodes; this screen lets the admin
either confirm (`kg.confirm_node`) or reject (delete + drop edges) each entry.

For Persons: split confirm actions — Confirm as Employee / as External, since
`Person.kind` drives downstream behavior (tier defaults, edge semantics).
External confirm prompts for `external_company` via inline input.
"""
from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static

import config
from core.ingestion_pipeline import get_kg


class PendingScreen(Screen):
    """Audit queue — class name kept for backward compat with main.py imports."""

    BINDINGS = [("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #F5A623]Audit queue[/] [dim]unconfirmed entries (auto-promoted, awaiting review)[/]",
            classes="section-title",
        )
        yield Static("", id="p-banner")
        with Horizontal(classes="split-pane"):
            with VerticalScroll(classes="split-pane-left"):
                with Horizontal(id="p-actions"):
                    yield Button("✓ Employee", variant="success", id="p-promote-emp")
                    yield Button("✓ External", variant="primary", id="p-promote-ext")
                    yield Button("✓ Confirm",  variant="default", id="p-promote-other")
                    yield Button("✗ Reject (delete)", variant="error", id="p-reject")
                with Horizontal(id="p-tier-row"):
                    yield Static("[#F5A623]Tier (Person):[/]", id="p-tier-label")
                    yield Select(
                        options=[(t, t) for t in config.TIERS],
                        id="p-tier",
                        prompt="tier",
                        value=config.DEFAULT_PERSON_TIER,
                        allow_blank=False,
                    )
                yield DataTable(id="p-table", zebra_stripes=True)
                yield Static("", id="p-extform")
            with VerticalScroll(classes="split-pane-right"):
                yield Static("[dim]select a row[/]", id="p-detail")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#p-table", DataTable)
        table.add_columns("id", "type", "name", "hint")
        table.cursor_type = "row"
        self.refresh_list()

    def on_screen_resume(self) -> None:
        self.refresh_list()

    def action_refresh(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        kg = get_kg()
        items = kg.list_unconfirmed()
        table = self.query_one("#p-table", DataTable)
        table.clear()
        for n in items:
            f = n["fields"]
            name = f.get("name") or f.get("title") or "—"
            hint = f.get("audit_hint") or n["entity_type"]
            table.add_row(
                n["id"][:24],
                n["entity_type"],
                str(name),
                hint,
            )
        self.query_one("#p-banner", Static).update(
            f"[#F5D020]{len(items)}[/] unconfirmed — select row, confirm or reject"
        )
        self.query_one("#p-extform", Static).update("")

    def _current_row(self) -> dict | None:
        table = self.query_one("#p-table", DataTable)
        if table.cursor_row is None or table.cursor_row < 0:
            return None
        items = get_kg().list_unconfirmed()
        if not items or table.cursor_row >= len(items):
            return None
        return items[table.cursor_row]

    @on(DataTable.RowHighlighted)
    def on_row(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is None or event.cursor_row < 0:
            return
        node = self._current_row()
        if not node:
            self.query_one("#p-detail", Static).update("[dim]no rows[/]")
            return
        self.query_one("#p-detail", Static).update(self._friendly_detail(node))

    def _friendly_detail(self, node: dict) -> str:
        et = node["entity_type"]
        f = node["fields"]
        name = f.get("name") or f.get("title") or "(unnamed)"
        lines = [
            f"[bold #5BC8F5]▌ {name}[/]",
            f"[dim]{et}  ·  {node['id']}[/]",
            f"[#F5D020]confirmed:[/] no (auto-promoted)",
            "",
        ]
        if et == "Person":
            kind = f.get("kind", "unknown")
            lines.append(f"  [#F5A623]kind:[/] [bold]{kind}[/]")
            tier = f.get("tier", config.DEFAULT_PERSON_TIER)
            tier_badge = " [#2ECC71](confirmed)[/]" if f.get("tier_confirmed") else " [#F5D020](unconfirmed)[/]"
            lines.append(f"  [#F5A623]tier:[/] [bold]{tier}[/]{tier_badge}")
            emails = f.get("emails") or []
            if emails:
                lines.append(f"  [#F5A623]emails:[/] {', '.join(emails)}")
            if f.get("role"):
                lines.append(f"  [#F5A623]role:[/] {f['role']}")
        elif et == "Team":
            lines.append(f"  [#F5A623]kind:[/] [bold]{f.get('kind', 'internal')}[/]")
            if f.get("external_org"):
                lines.append(f"  [#F5A623]org:[/] {f['external_org']}")
            if f.get("mission"):
                lines.append(f"  [#F5A623]mission:[/] {f['mission']}")
        elif et == "Project":
            lines.append(f"  [#F5A623]kind:[/] [bold]{f.get('kind', 'internal')}[/]")
            if f.get("status"):
                lines.append(f"  [#F5A623]status:[/] {f['status']}")
            if f.get("lead"):
                lines.append(f"  [#F5A623]lead:[/] {f['lead']}")
            if f.get("client_id"):
                lines.append(f"  [#F5A623]client_id:[/] {f['client_id']}")
        elif et == "Client":
            if f.get("industry"):
                lines.append(f"  [#F5A623]industry:[/] {f['industry']}")
            if f.get("domicile"):
                lines.append(f"  [#F5A623]domicile:[/] {f['domicile']}")
            if f.get("contact_email"):
                lines.append(f"  [#F5A623]contact:[/] {f['contact_email']}")
        elif et == "Rule":
            lines.append(f"  [#F5A623]category:[/] {f.get('category', '—')}")
            if f.get("content"):
                content = f["content"]
                if len(content) > 200:
                    content = content[:200] + "…"
                lines.append(f"  [#F5A623]content:[/] {content}")
        elif et == "Event":
            if f.get("date"):
                lines.append(f"  [#F5A623]date:[/] {f['date']}")
            if f.get("outcome"):
                lines.append(f"  [#F5A623]outcome:[/] {f['outcome']}")
        return "\n".join(lines)

    # ---- Confirm as Employee ----
    @on(Button.Pressed, "#p-promote-emp")
    def confirm_employee(self) -> None:
        node = self._current_row()
        if not node:
            return
        if node["entity_type"] != "Person":
            self.query_one("#p-banner", Static).update(
                "[red]Employee path only for Person rows[/]"
            )
            return
        self._confirm_person(node, kind="employee", external_company=None)

    # ---- Confirm as External — show inline form first ----
    @on(Button.Pressed, "#p-promote-ext")
    def confirm_external_step1(self) -> None:
        node = self._current_row()
        if not node:
            return
        if node["entity_type"] != "Person":
            self.query_one("#p-banner", Static).update(
                "[red]External path only for Person rows[/]"
            )
            return
        form = self.query_one("#p-extform", Static)
        form.update(
            f"[#F5A623]External company for[/] [bold]{node['fields'].get('name', '—')}[/]:\n"
            f"[dim]type below, press Enter[/]"
        )
        try:
            existing = self.query_one("#p-extform-input")
            existing.remove()
        except Exception:
            pass
        inp = Input(placeholder="e.g. Cambridge Associates", id="p-extform-input")
        form.mount(inp)
        inp.focus()
        self._pending_external_id = node["id"]

    @on(Input.Submitted, "#p-extform-input")
    def confirm_external_step2(self, event: Input.Submitted) -> None:
        company = event.value.strip()
        node_id = getattr(self, "_pending_external_id", None)
        if not company or not node_id:
            self.query_one("#p-banner", Static).update("[red]missing company[/]")
            return
        items = get_kg().list_unconfirmed()
        node = next((n for n in items if n["id"] == node_id), None)
        if not node:
            self.query_one("#p-banner", Static).update("[red]row gone[/]")
            return
        self._confirm_person(node, kind="external", external_company=company)
        self.query_one("#p-extform", Static).update("")
        try:
            self.query_one("#p-extform-input").remove()
        except Exception:
            pass
        self._pending_external_id = None

    # ---- Confirm (other entity types) ----
    @on(Button.Pressed, "#p-promote-other")
    def confirm_other(self) -> None:
        node = self._current_row()
        if not node:
            return
        if node["entity_type"] == "Person":
            self.query_one("#p-banner", Static).update(
                "[red]For Person, use Employee or External buttons[/]"
            )
            return
        kg = get_kg()
        admin = config.TELEGRAM_ADMIN_CHAT_ID or "tui-admin"
        kg.confirm_node(node["id"], by=admin)
        self.refresh_list()
        self.query_one("#p-banner", Static).update(
            f"[#2ECC71]confirmed[/] {node['entity_type']} → {node['id']}"
        )

    # ---- Reject (delete from live graph) ----
    @on(Button.Pressed, "#p-reject")
    def reject(self) -> None:
        node = self._current_row()
        if not node:
            return
        kg = get_kg()
        result = kg.delete_node(node["id"])
        self.refresh_list()
        self.query_one("#p-banner", Static).update(
            f"[#E74C3C]rejected[/] {node['id']}  "
            f"(edges removed: {result.get('edges_removed', 0)})"
        )

    # ---- Internal: patch Person fields on live node, then confirm ----
    def _confirm_person(
        self, node: dict, *, kind: str, external_company: str | None
    ) -> None:
        kg = get_kg()
        admin = config.TELEGRAM_ADMIN_CHAT_ID or "tui-admin"
        kg.update_live_field(node["id"], "kind", kind)
        if external_company is not None:
            kg.update_live_field(node["id"], "external_company", external_company)
        # Tier picker — CEO is confirming tier at confirmation time
        tier_sel = self.query_one("#p-tier", Select).value
        if isinstance(tier_sel, str) and tier_sel in config.TIERS:
            kg.update_live_field(node["id"], "tier", tier_sel)
            kg.update_live_field(node["id"], "tier_confirmed", True)
        kg.confirm_node(node["id"], by=admin)
        self.refresh_list()
        suffix = f" at {external_company}" if external_company else ""
        self.query_one("#p-banner", Static).update(
            f"[#2ECC71]confirmed as {kind}[/] → {node['id']}{suffix}"
        )
