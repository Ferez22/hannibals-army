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

        # data can be str (legacy) or {"answer": str, "diag": dict}
        answer = result.data
        diag = None
        if isinstance(result.data, dict):
            answer = result.data.get("answer", "")
            diag = result.data.get("diag")

        # Retrieval stats line (yellow) — visible BEFORE the answer
        if diag:
            ents = diag.get("entities_found", "-")
            chunks = diag.get("chunks_found", "-")
            self.app.call_from_thread(
                log.write,
                f"[#F5D020]retrieved:[/] entities={ents}  chunks={chunks}",
            )
            scores = diag.get("top_chunk_scores", [])
            previews = diag.get("top_chunk_previews", [])
            for sc, p in zip(scores, previews):
                self.app.call_from_thread(
                    log.write,
                    f"[dim]  ▸ [rrf={sc['rrf']} bm25={sc['bm25']} dist={sc['dense_dist']}] {p}[/]",
                )

        self.app.call_from_thread(log.write, f"[#2ECC71]A:[/] {answer}")
        if result.cited_nodes:
            self.app.call_from_thread(
                log.write,
                f"[dim]cited {len(result.cited_nodes)} sources: {', '.join(result.cited_nodes[:5])}[/]",
            )
        self.app.call_from_thread(log.write, "")
