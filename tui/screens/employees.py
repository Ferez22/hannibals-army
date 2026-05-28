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
        all_persons = kg.list_live("Person")
        employees = [p for p in all_persons if p["fields"].get("kind") == "employee"]
        grid = self.query_one("#e-grid", Grid)
        for child in list(grid.children):
            child.remove()

        if not employees:
            self.query_one("#e-banner", Static).update(
                "[dim]no employees yet — classify pending persons as employee[/]"
            )
            return

        self.query_one("#e-banner", Static).update(
            f"[#5BC8F5]{len(employees)}[/] employees  "
            f"[dim](of {len(all_persons)} persons total)[/]"
        )

        for person in employees:
            grid.mount(self._build_card(person, kg))

    def _build_card(self, person: dict, kg) -> Vertical:
        fields = person["fields"]
        name = fields.get("name", "—")
        emails = fields.get("emails") or []
        email_display = emails[0] if emails else ""
        role = fields.get("role") or "—"
        sub_roles = fields.get("sub_roles") or []
        confidence = person["confidence"]
        conf_color = "#2ECC71" if confidence >= 0.6 else ("#F5A623" if confidence >= 0.3 else "#E74C3C")

        photo_abs = photo_store.get_photo_path(fields.get("photo_path"))

        # Teams: direct MEMBER_OF
        # Projects: 2-hop via Team → RUNS → Project, plus direct AUTHORED docs
        teams: list[tuple[str, str]] = []  # (team_id, label)
        for e in kg.neighbors(person["id"]):
            if e["from_id"] != person["id"]:
                continue
            target = kg.get_live(e["to_id"])
            if not target:
                continue
            tname = target["fields"].get("name") or target["fields"].get("title") or "—"
            if e["type"] == "MEMBER_OF" and target["entity_type"] == "Team":
                role_label = e["properties"].get("role")
                sub = e["properties"].get("sub_roles") or []
                tag = role_label or ""
                if sub:
                    tag = (tag + " · " if tag else "") + ", ".join(sub)
                label = f"{tname}" + (f" ({tag})" if tag else "")
                teams.append((target["id"], label))

        # 2-hop projects via teams the person is in
        projects: list[str] = []
        for team_id, _ in teams:
            for e2 in kg.neighbors(team_id):
                if e2["from_id"] != team_id or e2["type"] != "RUNS":
                    continue
                tgt = kg.get_live(e2["to_id"])
                if tgt and tgt["entity_type"] == "Project":
                    pname = tgt["fields"].get("name", "—")
                    if pname not in projects:
                        projects.append(pname)
        team_labels = [label for _, label in teams]
        # rebind for downstream code expecting `teams: list[str]`
        teams = team_labels  # type: ignore[assignment]

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
        ]
        if sub_roles:
            info_lines.append(f"[#F5D020]+ {', '.join(sub_roles)}[/]")
        if email_display:
            info_lines.append(f"[dim]{email_display}[/]")
        if len(emails) > 1:
            info_lines.append(f"[dim](+{len(emails) - 1} more)[/]")
        info_lines.append(f"confidence [{conf_color}]{confidence:.2f}[/]")
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
