"""Notifier — dispatches messages to rule owners and admins.

Channels:
  - TUI: queues a row in review_queue (kind='rule_notification') — visible in Review screen.
  - Telegram: posts to the admin chat configured in .env (single-admin MVP).

For MVP, all notifications go to TELEGRAM_ADMIN_CHAT_ID. Per-person routing
later (Person.telegram_chat_id field).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import config

if TYPE_CHECKING:
    from capabilities.graph_store import GraphStore

log = logging.getLogger("hannibal.notifier")

TELEGRAM_API_BASE = "https://api.telegram.org"


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def telegram_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN) and bool(config.TELEGRAM_ADMIN_CHAT_ID)


def send_telegram(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message to the admin chat. Returns True on success, False otherwise."""
    if not telegram_configured():
        log.warning("telegram_not_configured", extra={"reason": "missing token or chat_id"})
        return False
    import requests
    url = f"{TELEGRAM_API_BASE}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("telegram_sent", extra={"chars": len(text)})
        return True
    except Exception as e:
        log.exception("telegram_failed", extra={"error": str(e)})
        return False


# ---------------------------------------------------------------------------
# Rule owner notification — TUI queue + Telegram
# ---------------------------------------------------------------------------
def notify_rule_owner(
    graph: "GraphStore",
    *,
    company_id: str,
    rule_id: str,
    rule_title: str,
    notify_person_id: str | None,
    reason: str,
) -> int:
    """Queue a TUI review item AND fire a Telegram message. Returns queue id."""
    details: dict[str, Any] = {
        "rule_title": rule_title,
        "reason": reason,
        "channel": "tui+telegram",
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
    # Best-effort Telegram fire
    msg = (
        f"⚠ <b>Rule stale</b>\n"
        f"<b>{_escape(rule_title)}</b>\n"
        f"reason: <code>{_escape(reason)}</code>\n"
        f"id: <code>{rule_id}</code>"
    )
    send_telegram(msg)
    return qid


# ---------------------------------------------------------------------------
# Digest — DONNA's full-scan summary
# ---------------------------------------------------------------------------
def send_scan_digest(
    *,
    stale_rules: list[dict],
    stale_other: list[dict],
    new_conflicts: list[dict],
) -> bool:
    """Send a single Telegram message summarising the scan."""
    if not telegram_configured():
        return False
    total = len(stale_rules) + len(stale_other) + len(new_conflicts)
    if total == 0:
        msg = "✅ <b>Army scan</b>\nAll clean. No stale items, no conflicts."
    else:
        lines = [f"📋 <b>Army scan</b> — {total} item(s) need attention"]
        if stale_rules:
            lines.append(f"\n<b>Stale rules ({len(stale_rules)})</b>")
            for r in stale_rules[:10]:
                lines.append(f"  • {_escape(r.get('title', '—'))}")
            if len(stale_rules) > 10:
                lines.append(f"  • +{len(stale_rules) - 10} more")
        if stale_other:
            lines.append(f"\n<b>Stale entities ({len(stale_other)})</b>")
            for r in stale_other[:10]:
                lines.append(
                    f"  • [{r.get('entity_type', '?')}] {_escape(r.get('name', '—'))}"
                )
            if len(stale_other) > 10:
                lines.append(f"  • +{len(stale_other) - 10} more")
        if new_conflicts:
            lines.append(f"\n<b>Open conflicts ({len(new_conflicts)})</b>")
            for c in new_conflicts[:10]:
                lines.append(
                    f"  • [{c.get('entity_type', '?')}] {_escape(c.get('name', '—'))}"
                )
            if len(new_conflicts) > 10:
                lines.append(f"  • +{len(new_conflicts) - 10} more")
        lines.append("\nReview them in the TUI: <code>v</code>")
        msg = "\n".join(lines)
    return send_telegram(msg)


def _escape(s: str | None) -> str:
    """Telegram HTML escape — only & < > are reserved."""
    if not s:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
