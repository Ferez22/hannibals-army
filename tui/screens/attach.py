"""Attach Photo screen — pick a Person, give a path or URL, save."""
from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from capabilities import photo_store
from core.ingestion_pipeline import get_kg


class AttachScreen(Screen):
    BINDINGS = [("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #F5A623]Attach photo to person[/]  "
            "[dim]1) select person  2) paste file path or URL  3) Save[/]",
            classes="section-title",
        )
        yield Static("", id="a-banner")
        with Horizontal():
            yield DataTable(id="a-table", zebra_stripes=True)
            with Vertical(id="a-form"):
                yield Static("[dim]selected person:[/]", id="a-selected")
                yield Input(
                    placeholder="/path/to/image.jpg  or  https://...",
                    id="a-input",
                )
                yield Button("Save", variant="primary", id="a-save")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#a-table", DataTable)
        table.add_columns("id", "name", "has photo")
        table.cursor_type = "row"
        self.refresh_list()

    def action_refresh(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        kg = get_kg()
        persons = kg.list_live("Person")
        table = self.query_one("#a-table", DataTable)
        table.clear()
        for p in persons:
            name = p["fields"].get("name", "—")
            has_photo = "yes" if p["fields"].get("photo_path") else "—"
            table.add_row(p["id"][:24], str(name), has_photo)
        self.query_one("#a-banner", Static).update(
            f"[#5BC8F5]{len(persons)}[/] persons in graph"
        )

    def _current_person(self) -> dict | None:
        table = self.query_one("#a-table", DataTable)
        if table.cursor_row is None or table.cursor_row < 0:
            return None
        persons = get_kg().list_live("Person")
        if not persons or table.cursor_row >= len(persons):
            return None
        return persons[table.cursor_row]

    @on(DataTable.RowHighlighted)
    def on_row(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is None or event.cursor_row < 0:
            return
        person = self._current_person()
        if not person:
            return
        name = person["fields"].get("name", "—")
        current = person["fields"].get("photo_path") or "[dim]none[/]"
        self.query_one("#a-selected", Static).update(
            f"[bold #5BC8F5]{name}[/]\n"
            f"[dim]id:[/] {person['id']}\n"
            f"[dim]current photo:[/] {current}"
        )

    @on(Button.Pressed, "#a-save")
    @on(Input.Submitted, "#a-input")
    def trigger_save(self) -> None:
        person = self._current_person()
        if not person:
            self.query_one("#a-banner", Static).update("[red]no person selected[/]")
            return
        source = self.query_one("#a-input", Input).value.strip()
        if not source:
            self.query_one("#a-banner", Static).update("[red]enter path or URL[/]")
            return
        self.query_one("#a-banner", Static).update(f"[#F5D020]saving...[/] {source}")
        self.run_save(person["id"], source)

    @work(thread=True)
    def run_save(self, person_id: str, source: str) -> None:
        banner = self.query_one("#a-banner", Static)
        try:
            saved_path = photo_store.attach_photo(person_id, source)
        except Exception as e:
            self.app.call_from_thread(
                banner.update, f"[red]failed:[/] {type(e).__name__}: {e}"
            )
            return
        kg = get_kg()
        kg.update_live_field(person_id, "photo_path", str(saved_path))
        self.app.call_from_thread(
            banner.update, f"[#2ECC71]saved[/] {saved_path}"
        )
        self.app.call_from_thread(self.query_one("#a-input", Input).clear)
        self.app.call_from_thread(self.refresh_list)
