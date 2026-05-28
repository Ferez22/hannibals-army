"""Externals grid — non-employee persons (clients, contractors, partners)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

try:
    from textual_image.widget import Image
except Exception:
    Image = None  # type: ignore[assignment]

from capabilities import photo_store
from core.ingestion_pipeline import get_kg


class ExternalsScreen(Screen):
    BINDINGS = [("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #F5A623]Externals[/]  [dim]clients, contractors, partners[/]",
            classes="section-title",
        )
        yield Static("", id="x-banner")
        yield Grid(id="x-grid")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_grid()

    def on_screen_resume(self) -> None:
        self.refresh_grid()

    def action_refresh(self) -> None:
        self.refresh_grid()

    def refresh_grid(self) -> None:
        kg = get_kg()
        all_persons = kg.list_live("Person")
        externals = [p for p in all_persons if p["fields"].get("kind") == "external"]
        grid = self.query_one("#x-grid", Grid)
        for child in list(grid.children):
            child.remove()

        if not externals:
            self.query_one("#x-banner", Static).update(
                "[dim]no externals yet — classify pending persons as external[/]"
            )
            return

        self.query_one("#x-banner", Static).update(
            f"[#F5A623]{len(externals)}[/] externals  "
            f"[dim](of {len(all_persons)} persons total)[/]"
        )
        for person in externals:
            grid.mount(self._build_card(person, kg))

    def _build_card(self, person: dict, kg) -> Vertical:
        fields = person["fields"]
        name = fields.get("name", "—")
        emails = fields.get("emails") or []
        role = fields.get("role") or "—"
        ext_company = fields.get("external_company") or "—"
        confidence = person["confidence"]
        conf_color = "#2ECC71" if confidence >= 0.6 else ("#F5A623" if confidence >= 0.3 else "#E74C3C")

        photo_abs = photo_store.get_photo_path(fields.get("photo_path"))

        # Linked projects / teams (rare for externals but possible)
        linked: list[str] = []
        for e in kg.neighbors(person["id"]):
            if e["from_id"] != person["id"]:
                continue
            target = kg.get_live(e["to_id"])
            if not target:
                continue
            tname = target["fields"].get("name") or target["fields"].get("title") or "—"
            linked.append(f"{e['type']} → {target['entity_type']}: {tname}")

        if Image is not None and photo_abs:
            try:
                photo_widget = Image(photo_abs, classes="emp-photo")
            except Exception:
                photo_widget = Static("[dim][image error][/]", classes="emp-photo")
        else:
            photo_widget = Static("[dim][no photo][/]", classes="emp-photo")

        info_lines = [
            f"[bold #F5A623]{name}[/]",
            f"[#5BC8F5]@ {ext_company}[/]",
            f"[#F5A623]{role}[/]" if role != "—" else "",
        ]
        if emails:
            info_lines.append(f"[dim]{emails[0]}[/]")
        info_lines.append(f"confidence [{conf_color}]{confidence:.2f}[/]")
        info_widget = Static("\n".join(line for line in info_lines if line), classes="emp-info")

        header_row = Horizontal(photo_widget, info_widget, classes="emp-header")

        body_lines: list[str] = []
        if linked:
            body_lines.append("[#F5A623]linked[/]")
            body_lines.extend(f"  • {l}" for l in linked)
        else:
            body_lines.append("[dim]no links yet[/]")
        body_widget = Static("\n".join(body_lines), classes="emp-body")

        return Vertical(header_row, body_widget, classes="ext-card")
