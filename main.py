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

    _maybe_auto_scan(kg)


def _maybe_auto_scan(kg) -> None:
    """Trigger DONNA full scan if last scan > AUTO_SCAN_INTERVAL_HOURS ago.

    Runs synchronously during warmup (before TUI). Cheap unless many entities.
    """
    from datetime import datetime, timedelta
    last = kg.graph.last_scan_at(config.COMPANY_ID, kind="auto")
    threshold = datetime.now() - timedelta(hours=config.AUTO_SCAN_INTERVAL_HOURS)
    if last is not None and last > threshold:
        age_h = (datetime.now() - last).total_seconds() / 3600
        print(f"auto-scan skipped (last ran {age_h:.1f}h ago).", flush=True)
        return

    print("auto-scan running (DONNA full scan + telegram digest if configured)...", flush=True)
    from agents.donna import DONNA
    result = DONNA.invoke({"action": "scan_all"})
    if not result.success:
        print(f"auto-scan failed: {result.error}", flush=True)
        return
    d = result.data
    print(
        f"auto-scan done: stale_rules={len(d['stale_rules'])} "
        f"stale_other={len(d['stale_other'])} open_conflicts={len(d['open_conflicts'])}",
        flush=True,
    )


def main() -> int:
    setup_logging()
    warmup()
    from tui.app import HannibalsArmyApp
    HannibalsArmyApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
