"""Edges screen — manually create or delete edges between live nodes."""
from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Select, Static

from core.entity_types import EdgeType
from core.ingestion_pipeline import get_kg


EDGE_TYPES: list[str] = [
    "MEMBER_OF",          # Person → Team
    "RUNS",               # Team → Project
    "WORKS_ON",           # Team or Person → Project
    "PARTICIPATED_IN",    # Person → Event
    "AUTHORED",           # Person → Document
    "CHILD_OF",           # Team → Team
    "OWNED_BY",           # Rule → Person/Team  OR  Project → Client
    "BELONGS_TO_CLIENT",  # Person (external) → Client
]


class EdgesScreen(Screen):
    BINDINGS = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #F5A623]Edges[/]  [dim]link entities: select FROM, TYPE, TO → Create[/]",
            classes="section-title",
        )
        yield Static("", id="ed-banner")
        with Vertical(id="ed-form"):
            with Horizontal(classes="ed-row"):
                yield Static("FROM", classes="ed-label")
                yield Select(
                    options=[],
                    id="ed-from",
                    prompt="select source node",
                )
            with Horizontal(classes="ed-row"):
                yield Static("TYPE", classes="ed-label")
                yield Select(
                    options=[(t, t) for t in EDGE_TYPES],
                    id="ed-type",
                    prompt="select edge type",
                )
            with Horizontal(classes="ed-row"):
                yield Static("TO  ", classes="ed-label")
                yield Select(
                    options=[],
                    id="ed-to",
                    prompt="select target node",
                )
            with Horizontal(classes="ed-row"):
                yield Static("role", classes="ed-label")
                yield Input(placeholder="optional — primary role", id="ed-role")
            with Horizontal(classes="ed-row"):
                yield Static("subs", classes="ed-label")
                yield Input(placeholder="optional — sub-roles, comma-separated", id="ed-subroles")
            with Horizontal(classes="ed-row"):
                yield Button("Create edge", variant="primary", id="ed-create")
        yield Static("", id="ed-warning")
        yield Static("", id="ed-existing")
        yield Footer()

    def on_mount(self) -> None:
        self.populate_selects()

    def on_screen_resume(self) -> None:
        self.populate_selects()

    def populate_selects(self) -> None:
        kg = get_kg()
        options: list[tuple[str, str]] = []
        for et in ("Person", "Team", "Project", "Client", "Rule", "Event", "Document"):
            for n in kg.list_live(et):
                label = n["fields"].get("name") or n["fields"].get("title") or "(unnamed)"
                options.append((f"[{et}] {label}  ({n['id'][:18]})", n["id"]))
        from_select = self.query_one("#ed-from", Select)
        to_select = self.query_one("#ed-to", Select)
        from_select.set_options(options)
        to_select.set_options(options)
        self._refresh_existing()

    def _refresh_existing(self) -> None:
        kg = get_kg()
        with kg.graph.conn() as c:
            rows = c.execute(
                "SELECT id, from_id, type, to_id, properties_json FROM live_edges WHERE company_id = ? ORDER BY id DESC LIMIT 50",
                (kg.company_id,),
            ).fetchall()
        if not rows:
            self.query_one("#ed-existing", Static).update(
                "[dim]no edges yet[/]"
            )
            return
        lines = ["[bold #F5A623]recent edges[/]"]
        for r in rows:
            lines.append(
                f"  [dim]#{r['id']}[/]  {r['from_id'][:20]}  [#5BC8F5]{r['type']}[/]  {r['to_id'][:20]}"
            )
        self.query_one("#ed-existing", Static).update("\n".join(lines))

    @on(Button.Pressed, "#ed-create")
    def create_edge(self) -> None:
        kg = get_kg()
        from_id = self.query_one("#ed-from", Select).value
        edge_type = self.query_one("#ed-type", Select).value
        to_id = self.query_one("#ed-to", Select).value
        role = self.query_one("#ed-role", Input).value.strip()
        subs_raw = self.query_one("#ed-subroles", Input).value.strip()
        sub_roles = [s.strip() for s in subs_raw.split(",") if s.strip()] if subs_raw else []
        banner = self.query_one("#ed-banner", Static)
        warning = self.query_one("#ed-warning", Static)

        if from_id is None or from_id == Select.BLANK or not isinstance(from_id, str):
            banner.update("[red]pick a FROM node[/]"); return
        if edge_type is None or edge_type == Select.BLANK or not isinstance(edge_type, str):
            banner.update("[red]pick an edge TYPE[/]"); return
        if to_id is None or to_id == Select.BLANK or not isinstance(to_id, str):
            banner.update("[red]pick a TO node[/]"); return
        if from_id == to_id:
            banner.update("[red]FROM and TO must differ[/]"); return

        # External → Team warning (MEMBER_OF only): require second click
        if edge_type == "MEMBER_OF":
            from_node = kg.get_live(from_id)
            to_node = kg.get_live(to_id)
            if (from_node and from_node["fields"].get("kind") == "external"
                    and to_node and to_node["entity_type"] == "Team"):
                key = (from_id, to_id, edge_type)
                if getattr(self, "_ext_confirmed", None) != key:
                    self._ext_confirmed = key
                    warning.update(
                        "[bold #F5D020]⚠ Adding an EXTERNAL person to an internal Team.[/]\n"
                        "  Click [bold]Create edge[/] again to confirm."
                    )
                    return
        # Reset confirmation memory
        self._ext_confirmed = None
        warning.update("")

        props: dict = {}
        if role:
            props["role"] = role
        if sub_roles:
            props["sub_roles"] = sub_roles
        try:
            edge_id = kg.add_live_edge(
                from_id=from_id, type=edge_type, to_id=to_id, properties=props or None
            )
        except Exception as e:
            banner.update(f"[red]{type(e).__name__}: {e}[/]"); return

        # Field-sync side effects so downstream views (Clients, yaml_sync) see the link
        try:
            if edge_type == "OWNED_BY":
                from_node = kg.get_live(from_id)
                to_node = kg.get_live(to_id)
                # Project --OWNED_BY--> Client : also set Project.client_id
                if (from_node and from_node["entity_type"] == "Project"
                        and to_node and to_node["entity_type"] == "Client"):
                    kg.update_live_field(from_id, "client_id", to_id)
                    # If project still marked internal, flip to external
                    if from_node["fields"].get("kind") != "external":
                        kg.update_live_field(from_id, "kind", "external")
        except Exception as e:
            banner.update(f"[#F5A623]edge ok, field-sync warn:[/] {e}");
            # still continue with success flow below

        banner.update(f"[#2ECC71]created edge #{edge_id}[/]  {edge_type}")
        self.query_one("#ed-role", Input).clear()
        self.query_one("#ed-subroles", Input).clear()
        self._refresh_existing()
