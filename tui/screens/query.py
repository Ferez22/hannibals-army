"""Query screen — intent-routed chat with ORACLE.

Phase 12: persistent conversation per Person. The admin (CEO) is the implicit
sender on the TUI surface — same `_resolve_uploader_person_id` logic that
ingest uses. Reset button starts a fresh conversation.

When ORACLE returns a clarification, suggestion buttons appear below the input.
Clicking a button re-submits that suggestion as a new question.
"""
from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from rich.markdown import Markdown
from rich.markup import escape as rich_escape

import config
from agents.oracle import ORACLE
from capabilities import persona_store
from core.ingestion_pipeline import get_kg, _resolve_uploader_person_id


TUI_CHAT_ID = "tui-admin-session"  # single TUI surface, one persistent convo


class QueryScreen(Screen):
    BINDINGS = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("[bold #F5A623]Query ORACLE[/]  [dim]intent-routed, cited, memory-aware[/]",
                     classes="section-title")
        yield Static("", id="q-persona-banner")
        with Horizontal(id="q-input-row"):
            yield Input(placeholder="Ask anything about the company knowledge graph...", id="q-input")
            yield Button("Ask", variant="primary", id="q-btn")
            yield Button("Reset", variant="default", id="q-reset")
        yield Horizontal(id="q-suggestions")
        yield RichLog(id="q-log", highlight=True, markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        get_kg()  # ensure KG bound to ORACLE
        self._refresh_persona_banner()
        self.query_one("#q-input", Input).focus()

    def _sender(self) -> tuple[str | None, str]:
        """Resolve TUI sender (default: admin CEO) → (person_id, tier_label)."""
        kg = get_kg()
        pid = _resolve_uploader_person_id(kg)
        if not pid:
            return None, config.UNKNOWN_SENDER_TIER
        node = kg.get_live(pid)
        tier = (node["fields"].get("tier") if node else None) or config.UNKNOWN_SENDER_TIER
        return pid, tier

    def _refresh_persona_banner(self) -> None:
        pid, tier = self._sender()
        banner = self.query_one("#q-persona-banner", Static)
        if not pid:
            banner.update("[dim]TUI sender unresolved — register a Person with CEO role to enable persona[/]")
            return
        node = get_kg().get_live(pid)
        name = (node["fields"].get("name") if node else "?") if node else "?"
        persona = persona_store.load_persona(pid)
        has_persona = persona is not None
        marker = "[#2ECC71]🪶 persona loaded[/]" if has_persona else "[#F5D020]🪶 no persona yet[/]"
        banner.update(f"[#5BC8F5]you:[/] {name}  [dim]tier={tier}[/]  {marker}")

    @on(Button.Pressed, "#q-reset")
    def reset_conversation(self) -> None:
        kg = get_kg()
        n = kg.reset_conversation(chat_id=TUI_CHAT_ID, channel="tui")
        log = self.query_one("#q-log", RichLog)
        log.write(f"[#F5D020]— conversation reset ({n} closed) —[/]\n")
        self._clear_suggestions()

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
        label = str(event.button.label)
        self._submit(label)

    @work(thread=True)
    def run_query(self, question: str) -> None:
        log = self.query_one("#q-log", RichLog)
        kg = get_kg()
        sender_person_id, sender_tier = self._sender()

        # Open / reuse TUI conversation, persist user turn before invocation
        try:
            conv = kg.get_or_create_conversation(
                chat_id=TUI_CHAT_ID, channel="tui", person_id=sender_person_id,
            )
            kg.append_conversation_message(
                conversation_id=conv["id"], role="user", content=question,
            )
        except Exception as e:
            self.app.call_from_thread(log.write, f"[red]conversation open failed:[/] {e}")
            return

        try:
            result = ORACLE.invoke({
                "question": question,
                "sender_person_id": sender_person_id,
                "sender_tier": sender_tier,
                "conversation_id": conv["id"],
            })
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

        # Persist assistant turn (even if render fails, memory is safe)
        try:
            kg.append_conversation_message(
                conversation_id=conv["id"], role="assistant", content=answer,
                intent=diag.get("intent"), cited_ids=result.cited_nodes,
            )
        except Exception as e:
            self.app.call_from_thread(log.write, f"[red]persist assistant failed:[/] {e}")

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

        for p in diag.get("top_chunk_previews", []):
            self.app.call_from_thread(log.write, f"[dim]  ▸ {p}[/]")

        self.app.call_from_thread(log.write, "[#2ECC71]A:[/]")
        self.app.call_from_thread(log.write, Markdown(answer))
        if result.cited_nodes:
            preview = ", ".join(result.cited_nodes[:5])
            self.app.call_from_thread(
                log.write,
                f"[dim]cited {len(result.cited_nodes)} sources: {preview}[/]",
            )

        if suggestions:
            self.app.call_from_thread(self._render_suggestions, suggestions)
        self.app.call_from_thread(log.write, "")

    def _render_suggestions(self, suggestions: list[str]) -> None:
        container = self.query_one("#q-suggestions", Horizontal)
        for child in list(container.children):
            child.remove()
        for i, sug in enumerate(suggestions[:4]):
            container.mount(Button(sug, variant="default", id=f"q-sugg-{i}"))
