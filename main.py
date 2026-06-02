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

    _maybe_auto_backup()
    _maybe_auto_scan(kg)


def _maybe_auto_backup() -> None:
    """Take a backup if last backup > 24h ago. Cheap, runs once a day."""
    from datetime import datetime, timedelta
    backups_dir = config.REPO_ROOT / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    backups = sorted(backups_dir.glob("army-*.tar.gz"), reverse=True)
    if backups:
        latest_age = datetime.now() - datetime.fromtimestamp(backups[0].stat().st_mtime)
        if latest_age < timedelta(hours=24):
            print(f"auto-backup skipped (last ran {latest_age.total_seconds()/3600:.1f}h ago).", flush=True)
            return
    print("auto-backup running...", flush=True)
    try:
        sys.path.insert(0, str(config.REPO_ROOT / "scripts"))
        from backup import make_backup
        make_backup(tag="auto")
    except Exception as e:
        print(f"auto-backup failed: {e}", flush=True)


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
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-bot", action="store_true",
                        help="Also start the Telegram inbound polling loop (background thread)")
    args = parser.parse_args()

    setup_logging()
    warmup()

    bot_stop = None
    bot_thread = None
    if args.with_bot:
        from capabilities import telegram_bot, notifier
        if not notifier.telegram_configured():
            print("warning: --with-bot but TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_CHAT_ID missing. "
                  "Skipping bot.", flush=True)
        else:
            import threading
            bot_stop = threading.Event()
            bot_thread = telegram_bot.start(bot_stop)
            print(f"telegram bot started (model: {config.MASTER_MODEL}). "
                  f"Send /help to your bot.", flush=True)

    try:
        from tui.app import HannibalsArmyApp
        HannibalsArmyApp().run()
    finally:
        if bot_stop is not None:
            bot_stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
