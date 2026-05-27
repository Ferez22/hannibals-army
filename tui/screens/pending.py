"""Pending screen — staged entities awaiting promotion. Actions: Promote / Reject."""
from __future__ import annotations

import json

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from agents.cartographer import _entity_description
from core.ingestion_pipeline import get_kg


class PendingScreen(Screen):
    BINDINGS = [("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #F5A623]Pending entities[/] [dim]awaiting promotion[/]", classes="section-title")
        with Horizontal():
            with Vertical():
                yield DataTable(id="p-table", zebra_stripes=True)
                with Horizontal(id="p-actions"):
                    yield Button("Promote", variant="success", id="p-promote")
                    yield Button("Reject",  variant="error",   id="p-reject")
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
        self.query_one("#p-detail", Static).update(
            f"[#2ECC71]{len(pendings)}[/] pending — select row, then Promote or Reject"
        )

    def _current_row(self) -> dict | None:
        table = self.query_one("#p-table", DataTable)
        if table.cursor_row is None:
            return None
        pendings = get_kg().list_pending()
        if table.cursor_row >= len(pendings):
            return None
        return pendings[table.cursor_row]

    @on(DataTable.RowHighlighted)
    def on_row(self, event: DataTable.RowHighlighted) -> None:
        node = self._current_row()
        if not node:
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

    @on(Button.Pressed, "#p-promote")
    def promote(self) -> None:
        node = self._current_row()
        if not node:
            return
        kg = get_kg()
        desc = _entity_description(node["entity_type"], node["fields"])
        live_id = kg.promote(node["id"], desc)
        self.refresh_list()
        self.query_one("#p-detail", Static).update(
            f"[#2ECC71]promoted →[/] {live_id}"
        )

    @on(Button.Pressed, "#p-reject")
    def reject(self) -> None:
        node = self._current_row()
        if not node:
            return
        # Soft reject — flip status. Future: add to blacklist table.
        with get_kg().graph.conn() as c:
            c.execute(
                "UPDATE staging_nodes SET promotion_status = 'rejected' WHERE id = ?",
                (node["id"],),
            )
        self.refresh_list()
        self.query_one("#p-detail", Static).update("[#E74C3C]rejected[/]")
