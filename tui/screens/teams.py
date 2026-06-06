"""Teams screen — create teams, add/remove members.

Adding an external person to a team triggers an inline confirmation prompt.
"""
from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static

from core.ingestion_pipeline import get_kg


class TeamsScreen(Screen):
    BINDINGS = [("r", "refresh", "Refresh")]

    _last_selected_team_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold #F5A623]Teams[/]  [dim]create teams, manage members[/]",
            classes="section-title",
        )
        yield Static("", id="t-banner")
        with Horizontal(classes="split-pane"):
            with VerticalScroll(classes="split-pane-left"):
                yield DataTable(id="t-table", zebra_stripes=True)
                with Vertical(classes="team-card"):
                    yield Static("[bold #F5A623]Create team[/]", classes="card-title")
                    with Horizontal(classes="t-row"):
                        yield Input(placeholder="team name", id="t-new-name")
                        yield Input(placeholder="mission (optional)", id="t-new-mission")
                    with Horizontal(classes="t-row"):
                        yield Select(
                            options=[("internal", "internal"), ("external", "external")],
                            id="t-new-kind",
                            prompt="kind",
                            value="internal",
                            allow_blank=False,
                        )
                        yield Input(
                            placeholder="external org (only if external)",
                            id="t-new-extorg",
                        )
                    with Horizontal(classes="t-row"):
                        yield Select(options=[], id="t-new-parent", prompt="parent (optional)")
                        yield Button("Create", variant="primary", id="t-create")
            with VerticalScroll(classes="split-pane-right"):
                yield Static("[dim]select a team to manage members[/]", id="t-detail")
                with Vertical(classes="team-card"):
                    yield Static("[bold #2ECC71]Add member[/]", classes="card-title")
                    with Horizontal(classes="t-row"):
                        yield Select(options=[], id="t-add-person", prompt="pick person")
                    with Horizontal(classes="t-row"):
                        yield Input(placeholder="role (e.g. Lead)", id="t-add-role")
                        yield Input(placeholder="sub-roles (comma-separated)", id="t-add-subroles")
                    with Horizontal(classes="t-row"):
                        yield Button("Add member", variant="success", id="t-add")
                    yield Static("", id="t-warning")
                with Vertical(classes="team-card"):
                    yield Static("[bold #E74C3C]Remove member[/]", classes="card-title")
                    with Horizontal(classes="t-row"):
                        yield Select(options=[], id="t-rm-member", prompt="pick member")
                        yield Button("Remove", variant="error", id="t-rm")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#t-table", DataTable)
        table.add_columns("id", "name", "members")
        table.cursor_type = "row"
        self._render_teams_table()
        self._update_parent_dropdown()
        # Member dropdowns + detail update only when a team is selected
        self._update_for_selected_team(force=True)

    def on_screen_resume(self) -> None:
        self._render_teams_table()
        self._update_parent_dropdown()
        self._update_for_selected_team(force=True)

    def action_refresh(self) -> None:
        self._render_teams_table()
        self._update_parent_dropdown()
        self._update_for_selected_team(force=True)
        self.query_one("#t-banner", Static).update("[dim]refreshed[/]")

    # ---- Granular renderers (do NOT touch banner) ----
    def _render_teams_table(self) -> None:
        kg = get_kg()
        teams = kg.list_live("Team")
        table = self.query_one("#t-table", DataTable)
        # Remember which team was selected so we can restore the cursor
        prev_id = self._last_selected_team_id
        table.clear()
        restore_idx: int | None = None
        for idx, t in enumerate(teams):
            members = self._members(t["id"])
            name = t["fields"].get("name", "—")
            table.add_row(t["id"][:24], str(name), str(len(members)))
            if t["id"] == prev_id:
                restore_idx = idx
        if restore_idx is not None:
            try:
                table.move_cursor(row=restore_idx)
            except Exception:
                pass

    def _update_parent_dropdown(self) -> None:
        kg = get_kg()
        teams = kg.list_live("Team")
        parent_opts = [(t["fields"].get("name", "—"), t["id"]) for t in teams]
        self._set_options_preserve("#t-new-parent", parent_opts)

    def _update_for_selected_team(self, force: bool = False) -> None:
        """Update detail pane + add/remove dropdowns ONLY when team selection changes."""
        team = self._selected_team()
        team_id = team["id"] if team else None
        if not force and team_id == self._last_selected_team_id:
            return  # selection unchanged, no need to rebuild
        self._last_selected_team_id = team_id

        # Detail pane
        self._render_selected_team()

        kg = get_kg()
        member_ids: set[str] = set()
        if team:
            member_ids = {m["person"]["id"] for m in self._members(team["id"])}

        # Add dropdown: exclude existing members
        persons = kg.list_live("Person")
        add_opts: list[tuple[str, str]] = []
        for p in persons:
            if p["id"] in member_ids:
                continue
            label_kind = p["fields"].get("kind", "unknown")
            label = f"[{label_kind}] {p['fields'].get('name', '—')}"
            add_opts.append((label, p["id"]))
        self._set_options_preserve("#t-add-person", add_opts)

        # Remove dropdown: current members only
        rm_opts: list[tuple[str, str]] = []
        if team:
            for m in self._members(team["id"]):
                pf = m["person"]["fields"]
                rm_opts.append((f"[{pf.get('kind', '?')}] {pf.get('name', '—')}", m["person"]["id"]))
        self._set_options_preserve("#t-rm-member", rm_opts)

    def _set_options_preserve(self, selector: str, opts: list[tuple[str, str]]) -> None:
        """Set Select options, preserving current value if still in options."""
        sel = self.query_one(selector, Select)
        prev = sel.value
        sel.set_options(opts)
        if prev is not None and prev != Select.BLANK and any(v == prev for _, v in opts):
            try:
                sel.value = prev
            except Exception:
                pass

    def _members(self, team_id: str) -> list[dict]:
        kg = get_kg()
        members: list[dict] = []
        for e in kg.graph.edges_to(kg.company_id, team_id):
            if e["type"] != "MEMBER_OF":
                continue
            person = kg.get_live(e["from_id"])
            if person:
                members.append({"person": person, "edge": e})
        return members

    def _selected_team(self) -> dict | None:
        table = self.query_one("#t-table", DataTable)
        if table.cursor_row is None or table.cursor_row < 0:
            return None
        teams = get_kg().list_live("Team")
        if not teams or table.cursor_row >= len(teams):
            return None
        return teams[table.cursor_row]

    @on(DataTable.RowHighlighted)
    def on_row(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is None or event.cursor_row < 0:
            return
        # Only rebuild dropdowns + detail when team selection ACTUALLY changes
        self._update_for_selected_team()

    def _render_selected_team(self) -> None:
        team = self._selected_team()
        if not team:
            self.query_one("#t-detail", Static).update(
                "[dim]select a team to manage members[/]"
            )
            return
        members = self._members(team["id"])
        lines = [
            f"[bold #5BC8F5]{team['fields'].get('name', '—')}[/]",
            f"[dim]id:[/] {team['id']}",
            f"[dim]mission:[/] {team['fields'].get('mission') or '—'}",
            "",
            f"[bold #F5A623]members ({len(members)})[/]",
        ]
        if not members:
            lines.append("[dim]  none yet[/]")
        for m in members:
            kind = m["person"]["fields"].get("kind", "?")
            pname = m["person"]["fields"].get("name", "—")
            role = m["edge"]["properties"].get("role", "")
            sub = m["edge"]["properties"].get("sub_roles") or []
            tag = role
            if sub:
                tag = (tag + " · " if tag else "") + ", ".join(sub)
            lines.append(f"  • [{kind}] {pname}" + (f"  ({tag})" if tag else ""))
        self.query_one("#t-detail", Static).update("\n".join(lines))

    # ---- Create team ----
    @on(Button.Pressed, "#t-create")
    def create_team(self) -> None:
        name = self.query_one("#t-new-name", Input).value.strip()
        mission = self.query_one("#t-new-mission", Input).value.strip()
        kind_sel = self.query_one("#t-new-kind", Select).value
        kind = kind_sel if kind_sel in ("internal", "external") else "internal"
        external_org = self.query_one("#t-new-extorg", Input).value.strip()
        parent_sel = self.query_one("#t-new-parent", Select).value
        parent_id = (
            parent_sel
            if (parent_sel is not None and parent_sel != Select.BLANK and isinstance(parent_sel, str))
            else None
        )

        banner = self.query_one("#t-banner", Static)
        if not name:
            banner.update("[red]team name required[/]"); return
        if kind == "external" and not external_org:
            banner.update("[red]external team requires external_org[/]"); return

        kg = get_kg()
        # Stage + auto-promote (team creation is human-initiated)
        staging_id = kg.stage_entity(
            entity_type="Team",
            fields={
                "name": name,
                "kind": kind,
                "external_org": external_org or None,
                "mission": mission or None,
                "parent_team_id": parent_id,
                "lead_id": None,
                "domain": None,
            },
            doc_id=None,
            promotion_status="auto_eligible",
        )
        live_id = kg.promote(staging_id, f"Team {kind}: {name}")
        if parent_id:
            kg.add_live_edge(from_id=live_id, type="CHILD_OF", to_id=parent_id)
        # Clear inputs
        self.query_one("#t-new-name", Input).clear()
        self.query_one("#t-new-mission", Input).clear()
        self.query_one("#t-new-extorg", Input).clear()
        banner.update(f"[#2ECC71]created {kind} team[/] {name} → {live_id}")
        self._render_teams_table()
        self._update_parent_dropdown()
        self._update_for_selected_team(force=True)

    # ---- Add member ----
    @on(Button.Pressed, "#t-add")
    def add_member(self) -> None:
        banner = self.query_one("#t-banner", Static)
        warn = self.query_one("#t-warning", Static)
        warn.update("")

        # 1) Team must be selected
        team = self._selected_team()
        if not team:
            banner.update("[red]select a team from the left table first[/]")
            return

        # 2) Person must be picked
        person_sel = self.query_one("#t-add-person", Select).value
        if person_sel is None or person_sel == Select.BLANK or not isinstance(person_sel, str):
            banner.update("[red]pick a person from the dropdown[/]")
            return

        kg = get_kg()
        person = kg.get_live(person_sel)
        if not person:
            banner.update("[red]selected person no longer exists[/]")
            return

        # 3) Dedup — already a member?
        if kg.has_member_edge(person_sel, team["id"]):
            banner.update(
                f"[red]{person['fields'].get('name')} is already a member of {team['fields'].get('name')}[/]"
            )
            return

        # 4) External warning — require two-click confirm
        if person["fields"].get("kind") == "external":
            if getattr(self, "_external_confirmed_for", None) != (team["id"], person_sel):
                self._external_confirmed_for = (team["id"], person_sel)
                warn.update(
                    "[bold #F5D020]⚠ This person is EXTERNAL[/]\n"
                    "  Click [bold]Add member[/] again to confirm."
                )
                return
        self._external_confirmed_for = None

        # 5) Build properties
        role = self.query_one("#t-add-role", Input).value.strip() or None
        sub_raw = self.query_one("#t-add-subroles", Input).value.strip()
        sub_roles = [s.strip() for s in sub_raw.split(",") if s.strip()] if sub_raw else []
        props: dict = {}
        if role:
            props["role"] = role
        if sub_roles:
            props["sub_roles"] = sub_roles

        # 6) Insert
        try:
            kg.add_live_edge(
                from_id=person_sel,
                type="MEMBER_OF",
                to_id=team["id"],
                properties=props or None,
            )
        except Exception as e:
            banner.update(f"[red]add failed: {type(e).__name__}: {e}[/]")
            return

        # Field-sync: if role indicates lead, also set Team.lead_id so downstream
        # (ORACLE, yaml_sync) sees the lead without needing edge traversal.
        if role and any(k in role.lower() for k in ("lead", "head", "manager")):
            try:
                kg.update_live_field(team["id"], "lead_id", person_sel)
            except Exception:
                pass

        self.query_one("#t-add-role", Input).clear()
        self.query_one("#t-add-subroles", Input).clear()
        banner.update(
            f"[#2ECC71]added[/] {person['fields'].get('name')} to {team['fields'].get('name')}"
            + (f" ({role})" if role else "")
        )
        self._render_teams_table()
        self._update_for_selected_team(force=True)

    # ---- Remove member ----
    @on(Button.Pressed, "#t-rm")
    def remove_member(self) -> None:
        banner = self.query_one("#t-banner", Static)
        team = self._selected_team()
        if not team:
            banner.update("[red]select a team from the left table first[/]")
            return
        person_sel = self.query_one("#t-rm-member", Select).value
        if person_sel is None or person_sel == Select.BLANK or not isinstance(person_sel, str):
            banner.update("[red]pick a member to remove[/]")
            return
        kg = get_kg()
        person = kg.get_live(person_sel)
        try:
            removed = kg.remove_member_edge(person_sel, team["id"])
        except Exception as e:
            banner.update(f"[red]remove failed: {type(e).__name__}: {e}[/]")
            return
        if removed == 0:
            banner.update("[red]not a member[/]")
            return
        pname = person["fields"].get("name") if person else person_sel
        banner.update(
            f"[#2ECC71]removed[/] {pname} from {team['fields'].get('name')}"
        )
        self._render_teams_table()
        self._update_for_selected_team(force=True)
