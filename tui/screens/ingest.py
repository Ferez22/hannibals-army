"""Ingest screen — input path/URL, run pipeline, show live progress."""
from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from core.ingestion_pipeline import ingest


class IngestScreen(Screen):
    BINDINGS = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #F5A623]Ingest[/] — drop a file path or paste a URL", classes="section-title")
        with Horizontal():
            yield Input(placeholder="e.g. data/samples/Handbook (1).docx  or  https://example.com", id="ingest-input")
            yield Button("Go", variant="primary", id="ingest-btn")
        yield Static("", id="ingest-status", classes="dim")
        yield RichLog(id="ingest-log", highlight=True, markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#ingest-input", Input).focus()

    @on(Button.Pressed, "#ingest-btn")
    @on(Input.Submitted, "#ingest-input")
    def trigger(self) -> None:
        source = self.query_one("#ingest-input", Input).value.strip()
        if not source:
            self._set_status("[red]enter a path or URL[/]")
            return
        self._set_status(f"[#F5D020]running...[/] {source}")
        self.run_ingest(source)

    @work(thread=True)
    def run_ingest(self, source: str) -> None:
        log = self.query_one("#ingest-log", RichLog)
        self.app.call_from_thread(log.write, f"[#5BC8F5]→[/] {source}")
        try:
            result = ingest(source)
        except Exception as e:
            self.app.call_from_thread(log.write, f"[red]EXCEPTION:[/] {e}")
            self.app.call_from_thread(self._set_status, f"[red]failed: {e}[/]")
            return

        if not result.success:
            self.app.call_from_thread(log.write, f"[red]FAIL:[/] {result.error}")
            self.app.call_from_thread(self._set_status, f"[red]{result.error}[/]")
            return

        data = result.data
        promoted = data["extraction_summary"]["promoted"]
        staged = data["extraction_summary"]["staged"]
        corrob = data["extraction_summary"]["corroborated"]
        edges = data["extraction_summary"]["edges_added"]
        self.app.call_from_thread(log.write, f"[#2ECC71]promoted:[/] {promoted}")
        self.app.call_from_thread(log.write, f"[#F5D020]staged:[/] {staged}")
        self.app.call_from_thread(log.write, f"[dim]corroborated: {corrob}  edges: {edges}[/]")
        self.app.call_from_thread(self._set_status, "[#2ECC71]done[/]")
        self.app.call_from_thread(self.query_one("#ingest-input", Input).clear)

    def _set_status(self, text: str) -> None:
        self.query_one("#ingest-status", Static).update(text)
