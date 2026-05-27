"""Query screen — chat with ORACLE, show cited nodes."""
from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from agents.oracle import ORACLE
from core.ingestion_pipeline import get_kg


class QueryScreen(Screen):
    BINDINGS = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #F5A623]Query ORACLE[/]", classes="section-title")
        with Horizontal():
            yield Input(placeholder="Ask anything about the company knowledge graph...", id="q-input")
            yield Button("Ask", variant="primary", id="q-btn")
        yield RichLog(id="q-log", highlight=True, markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        get_kg()  # ensure KG bound to ORACLE
        self.query_one("#q-input", Input).focus()

    @on(Button.Pressed, "#q-btn")
    @on(Input.Submitted, "#q-input")
    def trigger(self) -> None:
        q = self.query_one("#q-input", Input).value.strip()
        if not q:
            return
        log = self.query_one("#q-log", RichLog)
        log.write(f"[#F5A623]Q:[/] {q}")
        log.write("[dim]thinking...[/]")
        self.run_query(q)
        self.query_one("#q-input", Input).clear()

    @work(thread=True)
    def run_query(self, question: str) -> None:
        log = self.query_one("#q-log", RichLog)
        try:
            result = ORACLE.invoke({"question": question})
        except Exception as e:
            self.app.call_from_thread(log.write, f"[red]EXCEPTION:[/] {e}")
            return

        if not result.success:
            self.app.call_from_thread(log.write, f"[red]FAIL:[/] {result.error}")
            return

        self.app.call_from_thread(log.write, f"[#2ECC71]A:[/] {result.data}")
        if result.cited_nodes:
            self.app.call_from_thread(
                log.write,
                f"[dim]cited {len(result.cited_nodes)} nodes: {', '.join(result.cited_nodes[:5])}[/]",
            )
        self.app.call_from_thread(log.write, "")
