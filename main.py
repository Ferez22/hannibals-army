"""Hannibal's Army — entry point. Launches the Textual TUI."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

import config
from tui.app import HannibalsArmyApp


def setup_logging() -> None:
    """File-only logging during TUI (Rich would corrupt the screen)."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        config.LOG_DIR / "army.log",
        maxBytes=10_000_000,
        backupCount=5,
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def main() -> int:
    setup_logging()
    HannibalsArmyApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
