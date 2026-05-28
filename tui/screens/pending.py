"""Pending screen — staged entities awaiting promotion.

For Persons: split actions — Promote as Employee / Promote as External.
External promotion asks for external_company first.
For all other types: single Promote button.
"""
from __future__ import annotations

import json

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

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
        with Horizontal():
            with Vertical():
                with Horizontal(id="p-actions"):
                    yield Button("Promote (Employee)", variant="success", id="p-promote-emp")
                    yield Button("Promote (External)", variant="primary", id="p-promote-ext")
                    yield Button("Promote (other)",    variant="default", id="p-promote-other")
                    yield Button("Reject",             variant="error",   id="p-reject")
                yield DataTable(id="p-table", zebra_stripes=True)
                yield Static("", id="p-extform")
            yield Static("", id="p-detail")
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
        lines = [
            f"[bold #5BC8F5]{node['id']}[/]",
            f"[dim]type:[/] {node['entity_type']}",
            f"[dim]reason:[/] {node['blocked_reason']}",
            f"[dim]doc:[/] {node['extracted_from_doc_id']}",
            "",
            "[bold #F5A623]fields[/]",
            json.dumps(node["fields"], indent=2, ensure_ascii=False),
        ]
        self.query_one("#p-detail", Static).update("\n".join(lines))

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
