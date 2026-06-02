"""Clients grid — paying customer organizations.

Each card shows name, status, industry, domicile, linked projects, confidence.
Cards have a yellow border to distinguish from employees / externals.
Bottom: manual "+ Create client" form (extractor does NOT auto-extract Clients
because they are high-stakes — user adds explicitly).
"""
from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Select, Static

from core.ingestion_pipeline import get_kg

STATUS_OPTS = [("active", "active"), ("paused", "paused"), ("closed", "closed")]


class ClientsScreen(Screen):
    BINDINGS = [("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #F5A623]Clients[/]  [dim]paying customer organizations[/]",
            classes="section-title",
        )
        yield Static("", id="cl-banner")
        with VerticalScroll(id="cl-scroll"):
            yield Grid(id="cl-grid")
            yield Static("[bold #F5A623]+ Create client[/]", classes="section-title")
            with Vertical(id="cl-form"):
                with Horizontal(classes="cl-row"):
                    yield Input(placeholder="name *", id="cl-name")
                    yield Input(placeholder="industry (optional)", id="cl-industry")
                with Horizontal(classes="cl-row"):
                    yield Input(placeholder="domicile (optional)", id="cl-domicile")
                    yield Input(placeholder="contact email (optional)", id="cl-email")
                with Horizontal(classes="cl-row"):
                    yield Select(options=STATUS_OPTS, value="active", id="cl-status")
                    yield Input(placeholder="notes (optional)", id="cl-notes")
                with Horizontal(classes="cl-row"):
                    yield Button("Create client", variant="primary", id="cl-create")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_grid()

    def on_screen_resume(self) -> None:
        self.refresh_grid()

    def action_refresh(self) -> None:
        self.refresh_grid()

    def refresh_grid(self) -> None:
        kg = get_kg()
        clients = kg.list_live("Client")
        grid = self.query_one("#cl-grid", Grid)
        for child in list(grid.children):
            child.remove()

        if not clients:
            self.query_one("#cl-banner", Static).update(
                "[dim]no clients yet — promote them in Pending[/]"
            )
            return

        self.query_one("#cl-banner", Static).update(
            f"[#F5D020]{len(clients)}[/] clients"
        )
        for c in clients:
            grid.mount(self._build_card(c, kg))

    def _build_card(self, client: dict, kg) -> Vertical:
        f = client["fields"]
        name = f.get("name", "—")
        status = f.get("status", "active")
        industry = f.get("industry") or "—"
        domicile = f.get("domicile") or "—"
        contact_email = f.get("contact_email") or ""
        notes = f.get("notes") or ""
        confidence = client["confidence"]
        conf_color = "#2ECC71" if confidence >= 0.6 else ("#F5A623" if confidence >= 0.3 else "#E74C3C")

        # Linked projects via Project.client_id OR OWNED_BY edge (Project → Client)
        linked_project_ids: set[str] = set()
        for p in kg.list_live("Project"):
            if p["fields"].get("client_id") == client["id"]:
                linked_project_ids.add(p["id"])
        for edge in kg.graph.edges_to(kg.company_id, client["id"]):
            if edge["type"] == "OWNED_BY":
                from_node = kg.get_live(edge["from_id"])
                if from_node and from_node["entity_type"] == "Project":
                    linked_project_ids.add(from_node["id"])
        linked_projects: list[str] = []
        for pid in linked_project_ids:
            p = kg.get_live(pid)
            if not p:
                continue
            pname = p["fields"].get("name", "—")
            pstatus = p["fields"].get("status") or "?"
            linked_projects.append(f"{pname} ({pstatus})")

        # Persons linked via BELONGS_TO_CLIENT
        linked_persons: list[str] = []
        for edge in kg.graph.edges_to(kg.company_id, client["id"]):
            if edge["type"] != "BELONGS_TO_CLIENT":
                continue
            person = kg.get_live(edge["from_id"])
            if person:
                linked_persons.append(person["fields"].get("name", "—"))

        status_color = {"active": "#2ECC71", "paused": "#F5A623", "closed": "#4A5568"}.get(status, "#FFFFFF")
        info_lines = [
            f"[bold #F5D020]{name}[/]",
            f"status [{status_color}]{status}[/]",
            f"[dim]industry:[/] {industry}",
            f"[dim]domicile:[/] {domicile}",
        ]
        if contact_email:
            info_lines.append(f"[dim]{contact_email}[/]")
        info_lines.append(f"confidence [{conf_color}]{confidence:.2f}[/]")
        info_widget = Static("\n".join(info_lines), classes="emp-info")

        header_row = Horizontal(info_widget, classes="emp-header")

        body_lines: list[str] = []
        if linked_projects:
            body_lines.append("[#F5A623]projects[/]")
            body_lines.extend(f"  • {p}" for p in linked_projects)
        if linked_persons:
            body_lines.append("[#F5A623]contacts[/]")
            body_lines.extend(f"  • {p}" for p in linked_persons)
        if not body_lines:
            body_lines.append("[dim]no linked projects or contacts[/]")
        if notes:
            body_lines.append("")
            body_lines.append(f"[dim]notes:[/] {notes}")
        body_widget = Static("\n".join(body_lines), classes="emp-body")

        return Vertical(header_row, body_widget, classes="client-card")

    # ---- Manual create ----
    @on(Button.Pressed, "#cl-create")
    def create_client(self) -> None:
        banner = self.query_one("#cl-banner", Static)
        name = self.query_one("#cl-name", Input).value.strip()
        if not name:
            banner.update("[red]name required[/]"); return

        industry = self.query_one("#cl-industry", Input).value.strip() or None
        domicile = self.query_one("#cl-domicile", Input).value.strip() or None
        email = self.query_one("#cl-email", Input).value.strip() or None
        status_sel = self.query_one("#cl-status", Select).value
        status = status_sel if status_sel in ("active", "paused", "closed") else "active"
        notes = self.query_one("#cl-notes", Input).value.strip() or None

        kg = get_kg()
        # Check duplicate by name
        for c in kg.list_live("Client"):
            if (c["fields"].get("name") or "").strip().lower() == name.lower():
                banner.update(f"[red]client '{name}' already exists[/]"); return

        # Stage + immediately promote (manual create = trusted)
        from agents.cartographer import _entity_description
        fields = {
            "name": name,
            "industry": industry,
            "domicile": domicile,
            "contact_email": email,
            "status": status,
            "notes": notes,
        }
        staging_id = kg.stage_entity(
            entity_type="Client",
            fields=fields,
            doc_id=None,
            promotion_status="auto_eligible",
        )
        live_id = kg.promote(staging_id, _entity_description("Client", fields))

        # Clear inputs
        for wid in ("#cl-name", "#cl-industry", "#cl-domicile", "#cl-email", "#cl-notes"):
            self.query_one(wid, Input).clear()
        banner.update(f"[#2ECC71]created[/] {name} → {live_id}")
        self.refresh_grid()
