"""Projects grid — internal + external initiatives the company runs.

Same pattern as Clients: manual create (extractor does NOT auto-extract Projects
because precision matters more than recall here — user explicitly defines them).
Optional Client picker creates the OWNED_BY edge automatically and flips
Project.kind to "external" + Project.client_id.
"""
from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Select, Static

from core.ingestion_pipeline import get_kg

KIND_OPTS = [("internal", "internal"), ("external", "external")]
STATUS_OPTS = [
    ("In Progress", "In Progress"),
    ("On Hold", "On Hold"),
    ("Done", "Done"),
    ("Cancelled", "Cancelled"),
]


class ProjectsScreen(Screen):
    BINDINGS = [("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #F5A623]Projects[/]  [dim]internal + external initiatives[/]",
            classes="section-title",
        )
        yield Static("", id="pj-banner")
        with VerticalScroll(id="pj-scroll"):
            yield Grid(id="pj-grid")
            yield Static("[bold #F5A623]+ Create project[/]", classes="section-title")
            with Vertical(id="pj-form"):
                with Horizontal(classes="pj-row"):
                    yield Input(placeholder="name *", id="pj-name")
                    yield Select(options=KIND_OPTS, value="internal", id="pj-kind")
                with Horizontal(classes="pj-row"):
                    yield Select(options=STATUS_OPTS, value="In Progress", id="pj-status")
                    yield Select(options=[], id="pj-client", prompt="client (external only)")
                with Horizontal(classes="pj-row"):
                    yield Input(placeholder="started (YYYY-MM-DD, optional)", id="pj-started")
                    yield Input(placeholder="target  (YYYY-MM-DD, optional)", id="pj-target")
                with Horizontal(classes="pj-row"):
                    yield Input(placeholder="description (optional)", id="pj-desc")
                with Horizontal(classes="pj-row"):
                    yield Button("Create project", variant="primary", id="pj-create")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_grid()
        self._refresh_client_dropdown()

    def on_screen_resume(self) -> None:
        self.refresh_grid()
        self._refresh_client_dropdown()

    def action_refresh(self) -> None:
        self.refresh_grid()
        self._refresh_client_dropdown()

    def _refresh_client_dropdown(self) -> None:
        kg = get_kg()
        opts = [(c["fields"].get("name", "—"), c["id"]) for c in kg.list_live("Client")]
        sel = self.query_one("#pj-client", Select)
        prev = sel.value
        sel.set_options(opts)
        if prev is not None and prev != Select.BLANK and any(v == prev for _, v in opts):
            try:
                sel.value = prev
            except Exception:
                pass

    def refresh_grid(self) -> None:
        kg = get_kg()
        projects = kg.list_live("Project")
        grid = self.query_one("#pj-grid", Grid)
        for child in list(grid.children):
            child.remove()
        if not projects:
            self.query_one("#pj-banner", Static).update(
                "[dim]no projects yet — fill the form below[/]"
            )
            return
        self.query_one("#pj-banner", Static).update(
            f"[#5BC8F5]{len(projects)}[/] projects"
        )
        for p in projects:
            grid.mount(self._build_card(p, kg))

    def _build_card(self, project: dict, kg) -> Vertical:
        f = project["fields"]
        name = f.get("name", "—")
        kind = f.get("kind", "internal")
        status = f.get("status") or "—"
        client_id = f.get("client_id")
        client_name = "—"
        if client_id:
            cl = kg.get_live(client_id)
            if cl:
                client_name = cl["fields"].get("name", "—")
        confidence = project["confidence"]
        conf_color = "#2ECC71" if confidence >= 0.6 else ("#F5A623" if confidence >= 0.3 else "#E74C3C")

        # Teams + persons WORKS_ON
        teams: list[str] = []
        persons: list[str] = []
        for edge in kg.graph.edges_to(kg.company_id, project["id"]):
            if edge["type"] not in ("WORKS_ON", "RUNS"):
                continue
            other = kg.get_live(edge["from_id"])
            if not other:
                continue
            nm = other["fields"].get("name", "—")
            if other["entity_type"] == "Team":
                teams.append(nm)
            elif other["entity_type"] == "Person":
                persons.append(nm)

        kind_color = "#F5D020" if kind == "external" else "#5BC8F5"
        status_color = {
            "In Progress": "#5BC8F5", "On Hold": "#F5A623",
            "Done": "#2ECC71", "Cancelled": "#4A5568",
        }.get(status, "#FFFFFF")

        info_lines = [
            f"[bold #F5A623]{name}[/]",
            f"kind [{kind_color}]{kind}[/]  ·  status [{status_color}]{status}[/]",
        ]
        if kind == "external":
            info_lines.append(f"[#F5D020]client:[/] {client_name}")
        if f.get("started") or f.get("target"):
            info_lines.append(f"[dim]{f.get('started') or '?'} → {f.get('target') or '?'}[/]")
        if f.get("description"):
            info_lines.append(f"[dim]{f['description']}[/]")
        info_lines.append(f"confidence [{conf_color}]{confidence:.2f}[/]")
        info_widget = Static("\n".join(info_lines), classes="emp-info")

        header_row = Horizontal(info_widget, classes="emp-header")

        body_lines: list[str] = []
        if teams:
            body_lines.append("[#F5A623]teams[/]")
            body_lines.extend(f"  • {t}" for t in teams)
        if persons:
            body_lines.append("[#F5A623]people[/]")
            body_lines.extend(f"  • {p}" for p in persons)
        if not body_lines:
            body_lines.append("[dim]no linked teams or people yet — use Edges to link[/]")
        body_widget = Static("\n".join(body_lines), classes="emp-body")

        return Vertical(header_row, body_widget, classes="project-card")

    @on(Button.Pressed, "#pj-create")
    def create_project(self) -> None:
        banner = self.query_one("#pj-banner", Static)
        name = self.query_one("#pj-name", Input).value.strip()
        if not name:
            banner.update("[red]name required[/]"); return

        kind_sel = self.query_one("#pj-kind", Select).value
        kind = kind_sel if kind_sel in ("internal", "external") else "internal"
        status_sel = self.query_one("#pj-status", Select).value
        status = status_sel if isinstance(status_sel, str) and status_sel != Select.BLANK else None
        started = self.query_one("#pj-started", Input).value.strip() or None
        target = self.query_one("#pj-target", Input).value.strip() or None
        desc = self.query_one("#pj-desc", Input).value.strip() or None

        client_sel = self.query_one("#pj-client", Select).value
        client_id = (
            client_sel
            if (client_sel is not None and client_sel != Select.BLANK and isinstance(client_sel, str))
            else None
        )

        if kind == "external" and not client_id:
            banner.update("[red]external project requires a client (pick from dropdown)[/]"); return

        kg = get_kg()
        # Dup check
        for p in kg.list_live("Project"):
            if (p["fields"].get("name") or "").strip().lower() == name.lower():
                banner.update(f"[red]project '{name}' already exists[/]"); return

        from agents.cartographer import _entity_description
        fields = {
            "name": name,
            "kind": kind,
            "status": status,
            "client_id": client_id,
            "started": started,
            "target": target,
            "description": desc,
            "lead": None,
            "team_id": None,
        }
        staging_id = kg.stage_entity(
            entity_type="Project",
            fields=fields,
            doc_id=None,
            promotion_status="auto_eligible",
        )
        live_id = kg.promote(staging_id, _entity_description("Project", fields), confirmed=True)

        # If external + client → auto-create OWNED_BY edge
        if kind == "external" and client_id:
            try:
                kg.add_live_edge(from_id=live_id, type="OWNED_BY", to_id=client_id)
            except Exception:
                pass

        # Clear inputs
        for wid in ("#pj-name", "#pj-started", "#pj-target", "#pj-desc"):
            self.query_one(wid, Input).clear()
        banner.update(f"[#2ECC71]created {kind} project[/] {name} → {live_id}")
        self.refresh_grid()
