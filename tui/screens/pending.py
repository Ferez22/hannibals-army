"""Pending screen — staged entities awaiting promotion.

For Persons: split actions — Promote as Employee / Promote as External.
External promotion asks for external_company first.
For all other types: single Promote button.
"""
from __future__ import annotations

import json

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static

import config

from agents.cartographer import _entity_description
from core.ingestion_pipeline import get_kg


class PendingScreen(Screen):
    BINDINGS = [("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #F5A623]Pending entities[/] [dim]awaiting promotion[/]",
            classes="section-title",
        )
        yield Static("", id="p-banner")
        with Horizontal(classes="split-pane"):
            with VerticalScroll(classes="split-pane-left"):
                with Horizontal(id="p-actions"):
                    yield Button("→ Employee", variant="success", id="p-promote-emp")
                    yield Button("→ External", variant="primary", id="p-promote-ext")
                    yield Button("→ Other",    variant="default", id="p-promote-other")
                    yield Button("Reject",     variant="error",   id="p-reject")
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
        table.add_columns("id", "type", "name", "reason")
        table.cursor_type = "row"
        self.refresh_list()

    def action_refresh(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        kg = get_kg()
        pendings = kg.list_pending()
        table = self.query_one("#p-table", DataTable)
        table.clear()
        for p in pendings:
            name = p["fields"].get("name") or p["fields"].get("title") or "—"
            table.add_row(
                p["id"][:24],
                p["entity_type"],
                str(name),
                p["blocked_reason"] or "—",
            )
        self.query_one("#p-banner", Static).update(
            f"[#2ECC71]{len(pendings)}[/] pending — select row, choose action"
        )
        self.query_one("#p-extform", Static).update("")

    def _current_row(self) -> dict | None:
        table = self.query_one("#p-table", DataTable)
        if table.cursor_row is None or table.cursor_row < 0:
            return None
        pendings = get_kg().list_pending()
        if not pendings or table.cursor_row >= len(pendings):
            return None
        return pendings[table.cursor_row]

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
            f"[#F5D020]reason:[/] {node['blocked_reason'] or '—'}",
            "",
        ]
        if et == "Person":
            kind = f.get("kind", "unknown")
            lines.append(f"  [#F5A623]kind:[/] [bold]{kind}[/]")
            tier = f.get("tier", config.DEFAULT_PERSON_TIER)
            confirmed = " [#2ECC71](confirmed)[/]" if f.get("tier_confirmed") else " [#F5D020](unconfirmed)[/]"
            lines.append(f"  [#F5A623]tier:[/] [bold]{tier}[/]{confirmed}")
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
        lines.append("")
        if node.get("extracted_from_doc_id"):
            lines.append(f"[dim]from doc: {node['extracted_from_doc_id']}[/]")
        return "\n".join(lines)

    # ---- Promote as Employee ----
    @on(Button.Pressed, "#p-promote-emp")
    def promote_employee(self) -> None:
        node = self._current_row()
        if not node:
            return
        if node["entity_type"] != "Person":
            self.query_one("#p-banner", Static).update(
                "[red]Promote (Employee) only for Person[/]"
            )
            return
        self._promote_person(node, kind="employee", external_company=None)

    # ---- Promote as External — show inline form first ----
    @on(Button.Pressed, "#p-promote-ext")
    def promote_external_step1(self) -> None:
        node = self._current_row()
        if not node:
            return
        if node["entity_type"] != "Person":
            self.query_one("#p-banner", Static).update(
                "[red]Promote (External) only for Person[/]"
            )
            return
        # Render mini form
        form = self.query_one("#p-extform", Static)
        form.update(
            f"[#F5A623]External company for[/] [bold]{node['fields'].get('name', '—')}[/]:\n"
            f"[dim]type below, press Enter[/]"
        )
        # Mount transient Input via call_later
        try:
            existing = self.query_one("#p-extform-input")
            existing.remove()
        except Exception:
            pass
        inp = Input(placeholder="e.g. Cambridge Associates", id="p-extform-input")
        form.mount(inp)
        inp.focus()
        self._pending_external_id = node["id"]  # remember which row

    @on(Input.Submitted, "#p-extform-input")
    def promote_external_step2(self, event: Input.Submitted) -> None:
        company = event.value.strip()
        node_id = getattr(self, "_pending_external_id", None)
        if not company or not node_id:
            self.query_one("#p-banner", Static).update("[red]missing company[/]")
            return
        # Find pending row
        pendings = get_kg().list_pending()
        node = next((n for n in pendings if n["id"] == node_id), None)
        if not node:
            self.query_one("#p-banner", Static).update("[red]row gone[/]")
            return
        self._promote_person(node, kind="external", external_company=company)
        self.query_one("#p-extform", Static).update("")
        try:
            self.query_one("#p-extform-input").remove()
        except Exception:
            pass
        self._pending_external_id = None

    # ---- Promote (other) — non-Person ----
    @on(Button.Pressed, "#p-promote-other")
    def promote_other(self) -> None:
        node = self._current_row()
        if not node:
            return
        if node["entity_type"] == "Person":
            self.query_one("#p-banner", Static).update(
                "[red]For Person, use Employee or External buttons[/]"
            )
            return
        kg = get_kg()
        desc = _entity_description(node["entity_type"], node["fields"])
        live_id = kg.promote(node["id"], desc)
        self.refresh_list()
        self.query_one("#p-banner", Static).update(
            f"[#2ECC71]promoted →[/] {live_id}"
        )

    # ---- Reject ----
    @on(Button.Pressed, "#p-reject")
    def reject(self) -> None:
        node = self._current_row()
        if not node:
            return
        with get_kg().graph.conn() as c:
            c.execute(
                "UPDATE staging_nodes SET promotion_status = 'rejected' WHERE id = ?",
                (node["id"],),
            )
        self.refresh_list()
        self.query_one("#p-banner", Static).update("[#E74C3C]rejected[/]")

    # ---- Internal: patch fields then promote ----
    def _promote_person(self, node: dict, *, kind: str, external_company: str | None) -> None:
        kg = get_kg()
        # Patch staging fields before promotion
        new_fields = dict(node["fields"])
        new_fields["kind"] = kind
        if external_company is not None:
            new_fields["external_company"] = external_company
        # Tier picker — CEO is confirming tier at promotion time
        tier_sel = self.query_one("#p-tier", Select).value
        if isinstance(tier_sel, str) and tier_sel in config.TIERS:
            new_fields["tier"] = tier_sel
            new_fields["tier_confirmed"] = True
        with kg.graph.conn() as c:
            c.execute(
                "UPDATE staging_nodes SET fields_json = ? WHERE id = ?",
                (json.dumps(new_fields), node["id"]),
            )
        desc = _entity_description("Person", new_fields)
        live_id = kg.promote(node["id"], desc)
        self.refresh_list()
        suffix = f" at {external_company}" if external_company else ""
        self.query_one("#p-banner", Static).update(
            f"[#2ECC71]promoted as {kind}[/] →  {live_id}{suffix}"
        )
