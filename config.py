"""Hannibal's Army — central config.

Single source of truth for paths, thresholds, models, tenancy.
No side effects on import (logging is set up explicitly in main.py).
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load .env into os.environ before reading
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
APP_NAME = "Hannibal's Army"
MASTER_MODEL = "gemma4:e2b"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# OpenAI fallback (used for synthesis on high-precision intents)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
# Default to gpt-4o-mini — cheap, broadly available. Override via OPENAI_MODEL env.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

# Per-intent synthesis model override. Falls back to MASTER_MODEL if intent not listed
# OR if OPENAI_API_KEY is empty.
SYNTHESIS_MODEL_MAP = {
    "rule":    "openai",
    "project": "openai",
    "company": "openai",
    "culture": "openai",
    "person":  "openai",   # weaving multi-edge person context — Gemma drops detail
    "team":    "openai",   # members + lead + projects narrative
    "client":  "openai",   # client + linked projects + contacts
    "event":   "openai",
    "document": "openai",  # quote synthesis benefits from cloud
    "summary": "openai",   # inventory-to-prose
}

# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------
COMPANY_ID = os.getenv("COMPANY_ID", "qartmina")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
DB_DIR = REPO_ROOT / "db"
DB_PATH = DB_DIR / "graph.db"
VECTOR_DIR = REPO_ROOT / "memory" / "chroma"
LOG_DIR = REPO_ROOT / "logs"
SAMPLES_DIR = REPO_ROOT / "data" / "samples"

# ---------------------------------------------------------------------------
# Profiles (YAML)
# ---------------------------------------------------------------------------
def _load_yaml(name: str) -> dict:
    path = REPO_ROOT / name
    if path.exists():
        with path.open() as f:
            return yaml.safe_load(f) or {}
    return {}


DIGITAL_TWIN = _load_yaml("digital-twin-config.yml")
COMPANY = _load_yaml("company-config.yml")

# ---------------------------------------------------------------------------
# Staleness thresholds (days) — DONNA uses these to flag stale entities
# ---------------------------------------------------------------------------
STALENESS_THRESHOLDS = {
    "person_role":         365,   # 12 months
    "team_structure":      180,   # 6 months
    "project_status":       90,   # 3 months
    "client_relationship": 180,   # 6 months — touch base regularly
    "rule_policy":         180,   # 6 months
    "event":              None,   # never
}

# ---------------------------------------------------------------------------
# Gemma4 vision token budgets — image_parser picks based on task
# ---------------------------------------------------------------------------
VISION_TOKEN_BUDGETS = {
    "caption":          70,
    "classification":  140,
    "document":        560,
    "ocr":            1120,
}

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
CHUNK_SIZE_TOKENS = 1500
CHUNK_OVERLAP_TOKENS = 200

# ---------------------------------------------------------------------------
# Staging + Promotion
# ---------------------------------------------------------------------------
PENDING_AUTO_PAUSE_THRESHOLD = 200    # ingestion_paused = True when exceeded
PENDING_REJECTED_BLACKLIST_DAYS = 90

# ---------------------------------------------------------------------------
# Notifications — Telegram
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()

# ---------------------------------------------------------------------------
# Auto-scan — DONNA full scan when last run > N hours ago
# ---------------------------------------------------------------------------
AUTO_SCAN_INTERVAL_HOURS = 24

# ---------------------------------------------------------------------------
# TUI palette
# ---------------------------------------------------------------------------
PALETTE = {
    "primary":   "#5BC8F5",  # light blue
    "text":      "#FFFFFF",
    "highlight": "#F5A623",  # orange
    "accent":    "#F5D020",  # yellow
    "danger":    "#E74C3C",  # red
    "success":   "#2ECC71",  # light green
    "dim":       "#4A5568",
    "bg":        "#0D1117",
}
