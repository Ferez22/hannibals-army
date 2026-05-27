"""SystemStatus — single boolean + counters. No state machine.

`ingestion_paused = True` when pending overload requires triage.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SystemStatus:
    ingestion_paused: bool = False
    pending_count: int = 0
    conflict_count: int = 0
    last_health_check: datetime | None = None
