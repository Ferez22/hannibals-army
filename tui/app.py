"""HannibalsArmyApp — Textual root."""
from __future__ import annotations

from textual.app import App

import config
from tui.screens.attach import AttachScreen
from tui.screens.browser import BrowserScreen
from tui.screens.edges import EdgesScreen
from tui.screens.employees import EmployeesScreen
from tui.screens.externals import ExternalsScreen
from tui.screens.home import HomeScreen
from tui.screens.ingest import IngestScreen
from tui.screens.pending import PendingScreen
from tui.screens.query import QueryScreen
from tui.screens.review import ReviewScreen
from tui.screens.teams import TeamsScreen
from tui.theme import CSS


class HannibalsArmyApp(App):
    CSS = CSS
    TITLE = config.APP_NAME
    SUB_TITLE = f"company: {config.COMPANY_ID}   model: {config.MASTER_MODEL}"

    SCREENS = {
        "home":      HomeScreen,
        "ingest":    IngestScreen,
        "query":     QueryScreen,
        "browser":   BrowserScreen,
        "pending":   PendingScreen,
        "review":    ReviewScreen,
        "attach":    AttachScreen,
        "employees": EmployeesScreen,
        "externals": ExternalsScreen,
        "teams":     TeamsScreen,
        "edges":     EdgesScreen,
    }

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("i", "goto('ingest')",    "Ingest"),
        ("q", "goto('query')",     "Query"),
        ("b", "goto('browser')",   "Browser"),
        ("p", "goto('pending')",   "Pending"),
        ("v", "goto('review')",    "Review"),
        ("e", "goto('employees')", "Employees"),
        ("x", "goto('externals')", "Externals"),
        ("t", "goto('teams')",     "Teams"),
        ("a", "goto('attach')",    "Attach"),
        ("g", "goto('edges')",     "Edges"),
        ("escape", "back",         "Back"),
    ]

    def on_mount(self) -> None:
        self.push_screen("home")

    def action_goto(self, name: str) -> None:
        # Don't stack the same screen on itself
        if self.screen_stack and self.screen_stack[-1].name == name:
            return
        self.push_screen(name)

    def action_back(self) -> None:
        # Never pop the Home screen — it's the root
        if isinstance(self.screen, HomeScreen):
            return
        if len(self.screen_stack) > 1:
            self.pop_screen()
