"""Employees grid — card per person with photo, name, role, teams, projects."""
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

try:
    from textual_image.widget import Image  # iTerm / Kitty / Sixel
except Exception:  # pragma: no cover — fallback for unsupported terminals
    Image = None  # type: ignore[assignment]

from capabilities import photo_store
from core.ingestion_pipeline import get_kg


class EmployeesScreen(Screen):
    BINDINGS = [("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #F5A623]Employees[/]  [dim]grid of profile cards[/]",
            classes="section-title",
        )
        yield Static("", id="e-banner")
        yield Grid(id="e-grid")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_grid()

    def action_refresh(self) -> None:
        self.refresh_grid()

    def on_screen_resume(self) -> None:
        self.refresh_grid()

    def refresh_grid(self) -> None:
        kg = get_kg()
        persons = kg.list_live("Person")
        grid = self.query_one("#e-grid", Grid)
        for child in list(grid.children):
            child.remove()

        if not persons:
            self.query_one("#e-banner", Static).update("[dim]no persons in graph[/]")
            return

        self.query_one("#e-banner", Static).update(
            f"[#5BC8F5]{len(persons)}[/] employees"
        )

        for person in persons:
            grid.mount(self._build_card(person, kg))

    def _build_card(self, person: dict, kg) -> Vertical:
        fields = person["fields"]
        name = fields.get("name", "—")
        email = fields.get("email") or ""
        role = fields.get("role") or "—"
        confidence = person["confidence"]
        conf_color = "#2ECC71" if confidence >= 0.6 else ("#F5A623" if confidence >= 0.3 else "#E74C3C")

        photo_abs = photo_store.get_photo_path(fields.get("photo_path"))

        # Collect memberships + projects via edges
        edges = kg.neighbors(person["id"])
        teams: list[str] = []
        projects: list[str] = []
        for e in edges:
            if e["from_id"] != person["id"]:
                continue
            target = kg.get_live(e["to_id"])
            if not target:
                continue
            tname = target["fields"].get("name") or target["fields"].get("title") or "—"
            if e["type"] == "MEMBER_OF" and target["entity_type"] == "Team":
                role_label = e["properties"].get("role")
                teams.append(f"{tname}" + (f" ({role_label})" if role_label else ""))
            elif e["type"] in ("RUNS", "AUTHORED") and target["entity_type"] == "Project":
                projects.append(tname)

        # Photo widget
        if Image is not None and photo_abs:
            try:
                photo_widget = Image(photo_abs, classes="emp-photo")
            except Exception:
                photo_widget = Static("[dim][image error][/]", classes="emp-photo")
        else:
            placeholder = "[dim][no photo][/]"
            photo_widget = Static(placeholder, classes="emp-photo")

        info_lines = [
            f"[bold #5BC8F5]{name}[/]",
            f"[#F5A623]{role}[/]" if role != "—" else "[dim]role unknown[/]",
            f"[dim]{email}[/]" if email else "",
            f"confidence [{conf_color}]{confidence:.2f}[/]",
        ]
        info_widget = Static(
            "\n".join(line for line in info_lines if line),
            classes="emp-info",
        )

        header_row = Horizontal(photo_widget, info_widget, classes="emp-header")

        # Teams + projects body
        body_lines: list[str] = []
        if teams:
            body_lines.append("[#F5A623]teams[/]")
            body_lines.extend(f"  • {t}" for t in teams)
        if projects:
            body_lines.append("[#F5A623]projects[/]")
            body_lines.extend(f"  • {p}" for p in projects)
        if not body_lines:
            body_lines.append("[dim]no team or project links yet[/]")
        body_widget = Static("\n".join(body_lines), classes="emp-body")

        return Vertical(header_row, body_widget, classes="emp-card")
