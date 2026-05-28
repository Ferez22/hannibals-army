"""Review screen — DONNA's queue: staleness + conflicts + rule notifications."""
from __future__ import annotations

import json

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from agents.donna import DONNA
from core.ingestion_pipeline import get_kg


class ReviewScreen(Screen):
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("s", "scan",    "Scan now"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #F5A623]Review queue[/]  [dim]conflicts, staleness, rule notifications[/]",
            classes="section-title",
        )
        yield Static("", id="r-banner")  # scan results, action confirmations
        with Horizontal():
            with Vertical():
                with Horizontal(id="r-actions"):
                    yield Button("Verify",         variant="success", id="r-verify")
                    yield Button("Add as sub-role", variant="primary", id="r-subrole")
                    yield Button("Replace role",   variant="warning", id="r-replace")
                    yield Button("Dismiss",        variant="default", id="r-dismiss")
                yield DataTable(id="r-table", zebra_stripes=True)
            yield Static("", id="r-detail")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#r-table", DataTable)
        table.add_columns("id", "kind", "type", "entity", "when")
        table.cursor_type = "row"
        self.refresh_list()

    def action_refresh(self) -> None:
        self.refresh_list()

    def action_scan(self) -> None:
        result = DONNA.invoke({"action": "scan_staleness"})
        banner = self.query_one("#r-banner", Static)
        if result.success:
            d = result.data
            if d["queued_review"] == 0 and d["queued_notifications"] == 0:
                banner.update("[#4A5568]scan complete — nothing stale right now[/]")
            else:
                banner.update(
                    f"[#2ECC71]scan complete[/]  "
                    f"staleness: [bold]{d['queued_review']}[/]   "
                    f"rule notifications: [bold]{d['queued_notifications']}[/]"
                )
        else:
            banner.update(f"[red]{result.error}[/]")
        self.refresh_list()

    def refresh_list(self) -> None:
        items = get_kg().graph.list_review_queue(get_kg().company_id)
        table = self.query_one("#r-table", DataTable)
        table.clear()
        for r in items:
            entity_label = r["details"].get("name") or r["details"].get("rule_title") or r["live_node_id"] or "—"
            when = r["created_at"][:16].replace("T", " ")
            kind_styles = {
                "conflict":          ("conflict",    "bold #E74C3C"),
                "staleness":         ("stale",       "bold #F5A623"),
                "rule_notification": ("rule-notify", "bold #F5D020"),
            }
            label, style = kind_styles.get(r["kind"], (r["kind"], ""))
            kind_cell = Text(label, style=style)
            table.add_row(
                str(r["id"]),
                kind_cell,
                r["entity_type"],
                str(entity_label)[:30],
                when,
            )
        self.query_one("#r-detail", Static).update(
            f"[#5BC8F5]{len(items)}[/] open items"
        )

    def _current(self) -> dict | None:
        table = self.query_one("#r-table", DataTable)
        if table.cursor_row is None or table.cursor_row < 0:
            return None
        items = get_kg().graph.list_review_queue(get_kg().company_id)
        if not items or table.cursor_row >= len(items):
            return None
        return items[table.cursor_row]

    @on(DataTable.RowHighlighted)
    def on_row(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is None or event.cursor_row < 0:
            return
        item = self._current()
        if not item:
            return
        lines = [
            f"[bold #5BC8F5]review #{item['id']}[/]",
            f"[dim]kind:[/] {item['kind']}",
            f"[dim]entity_type:[/] {item['entity_type']}",
            f"[dim]live_node_id:[/] {item['live_node_id']}",
            f"[dim]created:[/] {item['created_at']}",
            "",
            "[bold #F5A623]details[/]",
            json.dumps(item["details"], indent=2, ensure_ascii=False),
        ]
        self.query_one("#r-detail", Static).update("\n".join(lines))

    @on(Button.Pressed, "#r-verify")
    def verify(self) -> None:
        item = self._current()
        if not item:
            self.query_one("#r-banner", Static).update("[red]no row selected[/]")
            return
        # Verify = bump last_verified_at on the live node, resolve review
        kg = get_kg()
        live_id = item["live_node_id"]
        if live_id:
            from datetime import datetime
            with kg.graph.conn() as c:
                c.execute(
                    "UPDATE live_nodes SET last_verified_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), live_id),
                )
        kg.graph.resolve_review(item["id"])
        self.refresh_list()
        self.query_one("#r-banner", Static).update(
            f"[#2ECC71]verified[/] — {live_id} reset to now"
        )

    @on(Button.Pressed, "#r-subrole")
    def add_as_subrole(self) -> None:
        item = self._current()
        banner = self.query_one("#r-banner", Static)
        if not item:
            banner.update("[red]no row selected[/]"); return
        if item["kind"] != "role_conflict":
            banner.update("[red]this action is only for role_conflict items[/]"); return
        kg = get_kg()
        live = kg.get_live(item["live_node_id"])
        if not live:
            banner.update("[red]live node gone[/]"); return
        new_role = item["details"]["diffs"]["role"]["candidate"]
        sub_roles = list(live["fields"].get("sub_roles") or [])
        if new_role not in sub_roles:
            sub_roles.append(new_role)
        kg.update_live_field(live["id"], "sub_roles", sub_roles)
        kg.graph.resolve_review(item["id"])
        self.refresh_list()
        banner.update(f"[#2ECC71]added sub-role[/] {new_role!r} on {live['id']}")

    @on(Button.Pressed, "#r-replace")
    def replace_role(self) -> None:
        item = self._current()
        banner = self.query_one("#r-banner", Static)
        if not item:
            banner.update("[red]no row selected[/]"); return
        if item["kind"] != "role_conflict":
            banner.update("[red]this action is only for role_conflict items[/]"); return
        kg = get_kg()
        live = kg.get_live(item["live_node_id"])
        if not live:
            banner.update("[red]live node gone[/]"); return
        old_role = live["fields"].get("role")
        new_role = item["details"]["diffs"]["role"]["candidate"]
        # Move old primary role into sub_roles (so we don't lose it)
        sub_roles = list(live["fields"].get("sub_roles") or [])
        if old_role and old_role not in sub_roles and old_role != new_role:
            sub_roles.append(old_role)
        kg.update_live_field(live["id"], "role", new_role)
        kg.update_live_field(live["id"], "sub_roles", sub_roles)
        kg.graph.resolve_review(item["id"])
        self.refresh_list()
        banner.update(
            f"[#2ECC71]replaced primary role[/] {old_role!r} → {new_role!r} (old kept as sub-role)"
        )

    @on(Button.Pressed, "#r-dismiss")
    def dismiss(self) -> None:
        item = self._current()
        if not item:
            self.query_one("#r-banner", Static).update("[red]no row selected[/]")
            return
        get_kg().graph.resolve_review(item["id"])
        self.refresh_list()
        self.query_one("#r-banner", Static).update("[#4A5568]dismissed[/]")
