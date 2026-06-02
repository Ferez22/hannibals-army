"""Ingest screen — drop a path/URL, run pipeline, show friendly result card."""
from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from core.ingestion_pipeline import ingest


class IngestScreen(Screen):
    BINDINGS = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #F5A623]Ingest[/] — drop a file path or paste a URL",
            classes="section-title",
        )
        with Horizontal(id="ingest-input-row"):
            yield Input(
                placeholder="e.g. data/samples/Handbook (1).docx  or  https://example.com",
                id="ingest-input",
            )
            yield Button("Go", variant="primary", id="ingest-btn")
        yield Static("", id="ingest-status", classes="dim")
        with VerticalScroll(id="ingest-results"):
            yield Static("", id="ingest-card")
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
        # Wipe last card while a new ingest runs
        self.query_one("#ingest-card", Static).update("")
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

        card_text = self._build_card(result.data)
        self.app.call_from_thread(self.query_one("#ingest-card", Static).update, card_text)

        # Compact log entry (one line)
        ex = result.data["extraction_summary"]
        n_prom = sum(ex["promoted"].values())
        n_stag = sum(ex["staged"].values())
        self.app.call_from_thread(
            log.write,
            f"[#2ECC71]✓[/] {result.data.get('doc_title', source)}  "
            f"[#2ECC71]+{n_prom} live[/]  [#F5D020]+{n_stag} pending[/]  "
            f"[dim]corroborated {ex['corroborated']}, edges {ex['edges_added']}[/]",
        )
        self.app.call_from_thread(self._set_status, "[#2ECC71]done[/]")
        self.app.call_from_thread(self.query_one("#ingest-input", Input).clear)

    def _build_card(self, data: dict) -> str:
        title = data.get("doc_title") or data.get("document_id") or "(unknown doc)"
        summary = (data.get("summary") or "").strip() or "[dim](no summary generated)[/]"
        ex = data["extraction_summary"]
        promoted = ex["promoted"]
        staged = ex["staged"]

        # Two compact lines instead of dict dumps
        def _fmt_counts(counts: dict[str, int]) -> str:
            items = [f"[bold]{v}[/] {k}" for k, v in counts.items() if v]
            return ", ".join(items) if items else "[dim]—[/]"

        prom_line = _fmt_counts(promoted)
        stag_line = _fmt_counts(staged)

        next_hints: list[str] = []
        if sum(staged.values()) > 0:
            next_hints.append("press [#5BC8F5]p[/] to triage pending")
        if sum(promoted.values()) > 0:
            next_hints.append("press [#5BC8F5]b[/] to browse the graph")
        if not next_hints:
            next_hints.append("nothing new — try another doc")
        hints = "  ·  ".join(next_hints)

        return (
            "\n"
            f"[bold #5BC8F5]▌ {title}[/]\n"
            f"[#F5D020]summary:[/] {summary}\n"
            "\n"
            f"[#2ECC71]✓ promoted to live :[/]   {prom_line}\n"
            f"[#F5A623]⏳ awaiting review :[/]   {stag_line}\n"
            f"[dim]↻ corroborated     :   {ex['corroborated']} existing nodes  ·  "
            f"edges added: {ex['edges_added']}[/]\n"
            "\n"
            f"[dim]{hints}[/]\n"
        )

    def _set_status(self, text: str) -> None:
        self.query_one("#ingest-status", Static).update(text)
