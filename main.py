"""Hannibal's Army — entry point. Launches the Textual TUI.

KG initialization happens BEFORE the TUI starts. sentence-transformers spawns
multiprocessing workers that conflict with Textual's event loop on Python 3.13,
so we pay the load cost upfront in the main process.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# Block torch / transformers from spawning helper processes inside Textual.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import config


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


def warmup() -> None:
    """Force model + DB load before Textual takes over the event loop."""
    print("loading knowledge graph (first run downloads embedding model)...", flush=True)
    from core.ingestion_pipeline import get_kg

    kg = get_kg()
    # Force the embedder to actually load weights now, not lazily.
    kg.vectors.search(query="warmup", company_id=config.COMPANY_ID, k=1)
    print("ready.", flush=True)


def main() -> int:
    setup_logging()
    warmup()
    from tui.app import HannibalsArmyApp
    HannibalsArmyApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
