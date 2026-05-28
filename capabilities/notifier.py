"""Notifier — dispatches messages to rule owners and admins.

MVP: writes to a notifications table (visible in TUI).
Future: Telegram, email, etc. behind feature flag.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from capabilities.graph_store import GraphStore

log = logging.getLogger("hannibal.notifier")


# Reuse review_queue table with kind='notification' to keep schema simple
def notify_rule_owner(
    graph: "GraphStore",
    *,
    company_id: str,
    rule_id: str,
    rule_title: str,
    notify_person_id: str | None,
    reason: str,
) -> int:
    """Queue a notification for a rule owner. Returns queue id."""
    details: dict[str, Any] = {
        "rule_title": rule_title,
        "reason": reason,
        "channel": "tui",  # future: telegram, email
        "created_at": datetime.now().isoformat(),
    }
    qid = graph.queue_for_review(
        company_id=company_id,
        kind="rule_notification",
        entity_type="Rule",
        live_node_id=rule_id,
        candidate_node_id=notify_person_id,
        details=details,
    )
    log.info(
        "rule_notification_queued",
        extra={"rule_id": rule_id, "notify_person_id": notify_person_id},
    )
    return qid
