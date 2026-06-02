"""Query screen — intent-routed chat with ORACLE.

When ORACLE returns a clarification, suggestion buttons appear below the input.
Clicking a button re-submits that suggestion as a new question.
"""
from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from rich.markup import escape as rich_escape

from agents.oracle import ORACLE
from core.ingestion_pipeline import get_kg


class QueryScreen(Screen):
    BINDINGS = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #F5A623]Query ORACLE[/]  [dim]intent-routed, cited[/]",
                     classes="section-title")
        with Horizontal(id="q-input-row"):
            yield Input(placeholder="Ask anything about the company knowledge graph...", id="q-input")
            yield Button("Ask", variant="primary", id="q-btn")
        yield Horizontal(id="q-suggestions")
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
        self._submit(q)

    def _submit(self, q: str) -> None:
        log = self.query_one("#q-log", RichLog)
        log.write(f"[#F5A623]Q:[/] {rich_escape(q)}")
        log.write("[dim]thinking...[/]")
        self._clear_suggestions()
        self.run_query(q)
        self.query_one("#q-input", Input).clear()

    def _clear_suggestions(self) -> None:
        container = self.query_one("#q-suggestions", Horizontal)
        for child in list(container.children):
            child.remove()

    @on(Button.Pressed)
    def on_any_button(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if not btn_id.startswith("q-sugg-"):
            return
        # Suggestion button — submit its label as the new question
        label = str(event.button.label)
        self._submit(label)

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

        data = result.data if isinstance(result.data, dict) else {"answer": str(result.data)}
        answer = data.get("answer", "")
        diag = data.get("diag") or {}
        suggestions = data.get("suggestions") or []

        # Diagnostic line
        intent = diag.get("intent", "?")
        mode = diag.get("mode")
        chunks = diag.get("chunks_found", 0)
        ents = diag.get("entities_expanded", 0)
        blocks = diag.get("blocks", 0)
        if mode == "clarification":
            self.app.call_from_thread(
                log.write, f"[#F5D020]intent:[/] {intent}  [dim](needs clarification)[/]"
            )
        else:
            self.app.call_from_thread(
                log.write,
                f"[#F5D020]intent:[/] {intent}  "
                f"[dim]blocks={blocks} entities={ents} chunks={chunks}[/]",
            )

        # Chunk previews (only when useful)
        for p in diag.get("top_chunk_previews", []):
            self.app.call_from_thread(log.write, f"[dim]  ▸ {p}[/]")

        # Escape LLM-produced text so `[citation]` etc don't get parsed as Rich markup
        self.app.call_from_thread(log.write, f"[#2ECC71]A:[/] {rich_escape(answer)}")
        if result.cited_nodes:
            preview = ", ".join(result.cited_nodes[:5])
            self.app.call_from_thread(
                log.write,
                f"[dim]cited {len(result.cited_nodes)} sources: {preview}[/]",
            )

        # Render suggestion buttons if clarification mode
        if suggestions:
            self.app.call_from_thread(self._render_suggestions, suggestions)
        self.app.call_from_thread(log.write, "")

    def _render_suggestions(self, suggestions: list[str]) -> None:
        container = self.query_one("#q-suggestions", Horizontal)
        for child in list(container.children):
            child.remove()
        for i, sug in enumerate(suggestions[:4]):
            container.mount(Button(sug, variant="default", id=f"q-sugg-{i}"))
