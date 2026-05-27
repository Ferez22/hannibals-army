"""Hannibal's Army — central config.

Single source of truth for paths, thresholds, models, tenancy.
No side effects on import (logging is set up explicitly in main.py).
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
APP_NAME = "Hannibal's Army"
MASTER_MODEL = "gemma4:e2b"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

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
    "person_role":    365,   # 12 months
    "team_structure": 180,   # 6 months
    "project_status":  90,   # 3 months
    "rule_policy":    180,   # 6 months
    "event":         None,   # never
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
