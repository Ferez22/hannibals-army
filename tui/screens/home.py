"""Home screen — army roster, KG snapshot, status."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from agents import all_agents
from core.ingestion_pipeline import get_kg, get_status


class HomeScreen(Screen):
    BINDINGS = [("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="status-bar")
        with Vertical():
            yield Static("[bold #F5A623]Standing by[/]", classes="section-title")
            yield Static("", id="agents-block")
            yield Static("[bold #F5A623]Knowledge Graph[/]", classes="section-title")
            yield Static("", id="kg-block")
            yield Static("[bold #F5A623]Keys[/]", classes="section-title")
            yield Static(
                "  [#5BC8F5]i[/] ingest    "
                "[#5BC8F5]q[/] query    "
                "[#5BC8F5]b[/] browser    "
                "[#5BC8F5]p[/] pending    "
                "[#5BC8F5]v[/] review\n"
                "  [#5BC8F5]e[/] employees    "
                "[#5BC8F5]x[/] externals    "
                "[#5BC8F5]t[/] teams    "
                "[#5BC8F5]a[/] attach photo\n"
                "  [#5BC8F5]g[/] edges    "
                "[#5BC8F5]r[/] refresh    "
                "[#5BC8F5]ctrl+c[/] quit",
                classes="dim",
            )
        yield Footer()

    def on_mount(self) -> None:
        # Show placeholder immediately, defer heavy KG init
        lines = [
            f"  [#5BC8F5]●[/] [bold]{a.name:<14}[/] [dim]{a.tagline}[/]"
            for a in all_agents()
        ]
        self.query_one("#agents-block", Static).update("\n".join(lines))
        self.query_one("#kg-block", Static).update("[dim]initializing knowledge graph...[/]")
        self.query_one("#status-bar", Static).update("● starting...")
        self.set_timer(0.1, self.refresh_state)

    def action_refresh(self) -> None:
        self.refresh_state()

    def refresh_state(self) -> None:
        # Agents
        lines = [
            f"  [#5BC8F5]●[/] [bold]{a.name:<14}[/] [dim]{a.tagline}[/]"
            for a in all_agents()
        ]
        self.query_one("#agents-block", Static).update("\n".join(lines))

        # KG snapshot
        kg = get_kg()
        counts: list[str] = []
        for et in ["Person", "Team", "Project", "Rule", "Event", "Document"]:
            n = len(kg.list_live(et))
            counts.append(f"  {et:9s} [bold #5BC8F5]{n}[/]")
        pending = kg.pending_count()
        review = len(kg.graph.list_review_queue(kg.company_id))
        counts.append(f"  [#F5D020]Pending[/]   [bold]{pending}[/]")
        counts.append(f"  [#F5A623]Review[/]    [bold]{review}[/]")
        self.query_one("#kg-block", Static).update("\n".join(counts))

        # Status bar
        status = get_status()
        bar = self.query_one("#status-bar", Static)
        if status.ingestion_paused:
            bar.add_class("paused")
            bar.update(f"⚠ INGESTION PAUSED — pending {status.pending_count} (triage in Pending screen)")
        else:
            bar.remove_class("paused")
            bar.update(f"● READY    pending: {status.pending_count}    conflicts: {status.conflict_count}")
