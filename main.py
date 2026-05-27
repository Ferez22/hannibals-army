"""Hannibal's Army — entry point.

Phase 0: prints army ready message, verifies all imports resolve.
Phase 3 will replace this with the Textual TUI app.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from rich.console import Console
from rich.logging import RichHandler

import config
from agents import ALL_AGENTS


def setup_logging() -> None:
    """Configure stdlib logging: Rich for stderr, rotating file for disk."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RichHandler(rich_tracebacks=True, markup=True, show_path=False),
        RotatingFileHandler(
            config.LOG_DIR / "army.log",
            maxBytes=10_000_000,
            backupCount=5,
        ),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def main() -> int:
    setup_logging()
    log = logging.getLogger("hannibal.main")
    console = Console()

    console.print()
    console.print(f"[bold #5BC8F5]{config.APP_NAME}[/]  —  scaffold ready", justify="center")
    console.print(f"[dim]company: {config.COMPANY_ID}   model: {config.MASTER_MODEL}[/]", justify="center")
    console.print()

    console.print("[#F5A623]Standing by:[/]")
    for agent in ALL_AGENTS:
        console.print(f"  [#5BC8F5]●[/] [bold]{agent.name:<14}[/] [dim]{agent.tagline}[/]")

    console.print()
    console.print(f"[#2ECC71]✔[/] {len(ALL_AGENTS)} agents loaded")
    console.print(f"[dim]config: {config.REPO_ROOT}[/]")
    console.print()

    log.info("army_ready", extra={"agents": len(ALL_AGENTS)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
