"""Browser screen — list live entities, view detail + edges."""
from __future__ import annotations

import json

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from core.ingestion_pipeline import get_kg

ENTITY_TYPES = ["Person", "Team", "Project", "Rule", "Event", "Document"]


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
        with Horizontal():
            yield DataTable(id="b-table", zebra_stripes=True)
            yield Static("", id="b-detail")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#b-table", DataTable)
        table.add_columns("id", "name", "confidence")
        table.cursor_type = "row"
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
            table.add_row(n["id"][:24], str(name), f"[{color}]{conf:.2f}[/]")
        self.query_one("#b-detail", Static).update("[dim]select a row to inspect[/]")

    @on(DataTable.RowHighlighted)
    def on_row(self, event: DataTable.RowHighlighted) -> None:
        et = ENTITY_TYPES[self.current_type_idx]
        nodes = get_kg().list_live(et)
        if event.cursor_row >= len(nodes):
            return
        node = nodes[event.cursor_row]
        lines = [
            f"[bold #5BC8F5]{node['id']}[/]",
            f"[dim]type:[/] {node['entity_type']}",
            f"[dim]confidence:[/] {node['confidence']:.2f}",
            f"[dim]source_count:[/] {node['source_count']}",
            f"[dim]created:[/] {node['created_at']}",
            f"[dim]last_verified:[/] {node['last_verified_at']}",
            "",
            "[bold #F5A623]fields[/]",
            json.dumps(node["fields"], indent=2, ensure_ascii=False),
        ]
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
