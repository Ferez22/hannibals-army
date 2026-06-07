"""Telegram inbound — long-poll loop, slash commands, free-text → ORACLE, CEO config edits.

Auth model:
  - Admin chat (TELEGRAM_ADMIN_CHAT_ID from .env) is always recognized as CEO.
  - Other chat_ids must be linked to a Person via Person.telegram_chat_id (set
    by admin via /register <person_name_or_id>).
  - Edit privileges: CEO-level (admin OR Person.role contains ceo/cto/admin).

Long-poll runs in a background thread. Stop via stop_event.

Slash commands:
  /me                  — show how the bot identifies you
  /pending             — count of pending entities
  /scan                — DONNA full scan
  /register <name|id>  — admin only: link this chat to a Person
  /help                — list commands

Free text:
  → ORACLE classify intent
  → if intent=config_edit AND CEO: propose patch with [Confirm][Cancel] buttons
  → else: synthesize answer, send back
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import config
from capabilities import config_patch, notifier, text_render
from core.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hannibal.telegram_bot")

# Pending patches per chat — chat_id (str) → patch dict
# Lives in-process. Restart loses them; acceptable for MVP.
_PENDING_PATCHES: dict[str, dict] = {}


# ---------------------------------------------------------------------------
def start(stop_event: threading.Event | None = None) -> threading.Thread:
    """Start polling in a daemon thread. Returns the thread for join/inspection."""
    stop_event = stop_event or threading.Event()
    t = threading.Thread(target=_loop, args=(stop_event,), daemon=True, name="telegram-bot")
    t.start()
    return t


def _loop(stop_event: threading.Event) -> None:
    if not notifier.telegram_configured():
        log.warning("telegram_bot_not_configured")
        return
    log.info("telegram_bot_started")
    offset = 0
    while not stop_event.is_set():
        try:
            updates = notifier.get_updates(offset=offset, timeout=25)
        except Exception as e:
            log.exception("polling_error", extra={"error": str(e)})
            continue
        for u in updates:
            try:
                _handle_update(u)
            except Exception:
                log.exception("update_handler_failed", extra={"update_id": u.get("update_id")})
            offset = u["update_id"] + 1
    log.info("telegram_bot_stopped")


# ---------------------------------------------------------------------------
def _handle_update(u: dict) -> None:
    if "callback_query" in u:
        _handle_callback(u["callback_query"])
        return
    msg = u.get("message")
    if not msg:
        return
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return
    sender = _resolve_sender(chat_id, msg)
    log.info("inbound", extra={"chat_id": chat_id, "person": sender.get("display"),
                               "is_ceo": sender["is_ceo"]})

    if text.startswith("/"):
        _handle_command(text, chat_id, sender)
        return
    _handle_freetext(text, chat_id, sender)


def _resolve_sender(chat_id: str, msg: dict) -> dict:
    """Return {chat_id, person_id, person_name, is_ceo, tier, display}.

    Admin chat_id is always CEO. Other chats look up Person.telegram_chat_id.
    Tier resolution (Phase 10A):
      - admin → 'ceo'
      - Person with tier_confirmed=True → person.tier
      - Person without confirmation → UNKNOWN_SENDER_TIER (gate until CEO confirms)
      - unknown chat → UNKNOWN_SENDER_TIER
    """
    from core.ingestion_pipeline import get_kg
    kg = get_kg()

    is_admin = (chat_id == config.TELEGRAM_ADMIN_CHAT_ID)
    person_node = None
    for p in kg.list_live("Person"):
        if (p["fields"].get("telegram_chat_id") or "") == chat_id:
            person_node = p
            break

    name = ""
    role = ""
    person_tier = config.UNKNOWN_SENDER_TIER
    tier_confirmed = False
    if person_node:
        f = person_node["fields"]
        name = f.get("name", "")
        role = (f.get("role") or "").lower()
        subs = " ".join(s.lower() for s in (f.get("sub_roles") or []))
        role = role + " " + subs
        tier_confirmed = bool(f.get("tier_confirmed"))
        if tier_confirmed:
            person_tier = f.get("tier") or config.UNKNOWN_SENDER_TIER
    elif msg.get("from", {}).get("first_name"):
        name = msg["from"]["first_name"]

    is_ceo = is_admin or any(k in role for k in ("ceo", "cto", "founder", "admin"))
    # Admin is always CEO tier; other senders use their confirmed tier or fallback.
    effective_tier = "ceo" if is_admin else person_tier

    return {
        "chat_id": chat_id,
        "person_id": person_node["id"] if person_node else None,
        "person_name": name,
        "is_admin": is_admin,
        "is_ceo": is_ceo,
        "tier": effective_tier,
        "tier_confirmed": tier_confirmed or is_admin,
        "display": name or f"chat:{chat_id}",
    }


# ---------------------------------------------------------------------------
def _handle_command(text: str, chat_id: str, sender: dict) -> None:
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/help", "/start"):
        _reply_help(chat_id)
        return
    if cmd == "/me":
        _reply_me(chat_id, sender)
        return
    if cmd == "/pending":
        _reply_pending(chat_id)
        return
    if cmd == "/scan":
        _reply_scan(chat_id, sender)
        return
    if cmd == "/register":
        _reply_register(chat_id, sender, arg)
        return
    notifier.send_telegram(f"Unknown command: <code>{_esc(cmd)}</code>\nTry <code>/help</code>",
                           chat_id=chat_id)


def _reply_help(chat_id: str) -> None:
    notifier.send_telegram(
        "<b>Hannibal's Army bot</b>\n\n"
        "<code>/me</code>         how the bot sees you\n"
        "<code>/pending</code>    pending entities count\n"
        "<code>/scan</code>       run DONNA full scan\n"
        "<code>/register &lt;name&gt;</code>  (admin) link this chat to a Person\n"
        "<code>/help</code>       this message\n\n"
        "Or just type a question — I'll answer.",
        chat_id=chat_id,
    )


def _reply_me(chat_id: str, sender: dict) -> None:
    lines = [
        f"<b>chat_id</b>: <code>{chat_id}</code>",
        f"<b>person</b>: {_esc(sender['display'])}",
    ]
    if sender["person_id"]:
        lines.append(f"<b>person_id</b>: <code>{sender['person_id']}</code>")
    lines.append(f"<b>admin</b>: {'yes' if sender['is_admin'] else 'no'}")
    lines.append(f"<b>CEO privileges</b>: {'yes' if sender['is_ceo'] else 'no'}")
    lines.append(f"<b>tier</b>: <code>{_esc(sender.get('tier', 'everyone'))}</code>"
                 f"  {'(confirmed)' if sender.get('tier_confirmed') else '(unconfirmed → baseline)'}")
    notifier.send_telegram("\n".join(lines), chat_id=chat_id)


def _reply_pending(chat_id: str) -> None:
    from core.ingestion_pipeline import get_kg
    kg = get_kg()
    pending = kg.pending_count()
    by_type = {}
    for p in kg.list_pending():
        by_type[p["entity_type"]] = by_type.get(p["entity_type"], 0) + 1
    lines = [f"<b>Pending</b>: {pending}"]
    for t, n in by_type.items():
        lines.append(f"  • {_esc(t)}: {n}")
    notifier.send_telegram("\n".join(lines), chat_id=chat_id)


def _reply_scan(chat_id: str, sender: dict) -> None:
    from agents.donna import DONNA
    notifier.send_telegram("Scanning...", chat_id=chat_id)
    result = DONNA.invoke({"action": "scan_all"})
    if not result.success:
        notifier.send_telegram(f"Scan failed: {_esc(result.error or '')}", chat_id=chat_id)
        return
    d = result.data
    msg = (f"<b>Scan done</b>\n"
           f"• stale rules: {len(d['stale_rules'])}\n"
           f"• stale other: {len(d['stale_other'])}\n"
           f"• open conflicts: {len(d['open_conflicts'])}")
    notifier.send_telegram(msg, chat_id=chat_id)


def _reply_register(chat_id: str, sender: dict, arg: str) -> None:
    if not sender["is_admin"]:
        notifier.send_telegram("Only admin can /register chat_ids.", chat_id=chat_id)
        return
    if not arg:
        notifier.send_telegram("Usage: <code>/register &lt;person name or id&gt;</code>",
                               chat_id=chat_id)
        return
    from core.ingestion_pipeline import get_kg
    from capabilities import dedup
    kg = get_kg()
    persons = kg.list_live("Person")
    # Match by id or name
    target = None
    for p in persons:
        if p["id"] == arg:
            target = p
            break
        if dedup.tokens_match(dedup.normalize_tokens(arg),
                              dedup.normalize_tokens(p["fields"].get("name"))):
            target = p
            break
    if not target:
        notifier.send_telegram(f"No Person matched <code>{_esc(arg)}</code>.",
                               chat_id=chat_id)
        return
    kg.update_live_field(target["id"], "telegram_chat_id", chat_id)
    notifier.send_telegram(
        f"✔ Linked chat <code>{chat_id}</code> to <b>{_esc(target['fields'].get('name'))}</b> "
        f"(<code>{target['id']}</code>).",
        chat_id=chat_id,
    )


# ---------------------------------------------------------------------------
def _handle_freetext(text: str, chat_id: str, sender: dict) -> None:
    """Route free text → ORACLE. CEO-level edit instructions go through patch flow."""
    from agents.oracle import ORACLE
    from agents import oracle_intent

    intent_info = oracle_intent.classify(text)
    intent = intent_info["intent"]

    if intent == "config_edit":
        if not sender["is_ceo"]:
            notifier.send_telegram(
                "Editing the company config requires CEO privileges.\n"
                "Ask the admin to <code>/register</code> you with a leadership role.",
                chat_id=chat_id,
            )
            return
        _propose_edit(text, chat_id, sender)
        return

    # Regular query — pass sender tier + person_id for retrieval filter
    result = ORACLE.invoke({
        "question": text,
        "sender_person_id": sender.get("person_id"),
        "sender_tier": sender.get("tier"),
    })
    if not result.success:
        notifier.send_telegram(f"Error: {_esc(result.error or '')}", chat_id=chat_id)
        return
    data = result.data if isinstance(result.data, dict) else {"answer": str(result.data)}
    answer = data.get("answer", "")
    diag_intent = (data.get("diag") or {}).get("intent", "?")
    # Convert LLM markdown → Telegram HTML (handles **bold**, # headers, lists, code, links)
    rendered = text_render.markdown_to_telegram_html(answer)
    notifier.send_telegram(
        f"{rendered}\n\n<i>intent: {diag_intent}</i>",
        chat_id=chat_id,
    )


def _propose_edit(instruction: str, chat_id: str, sender: dict) -> None:
    patch = config_patch.propose_patch(instruction)
    if not patch:
        notifier.send_telegram(
            "I couldn't translate that into a config edit. Try being more specific, e.g.\n"
            "<code>remember our HQ is &lt;address&gt;</code>",
            chat_id=chat_id,
        )
        return
    if "error" in patch:
        notifier.send_telegram(f"Can't apply: {_esc(patch['error'])}", chat_id=chat_id)
        return

    # Stash patch + send confirm/cancel keyboard
    _PENDING_PATCHES[chat_id] = patch
    summary = patch.get("human_summary", "Edit pending")
    body = (
        f"<b>Proposed change</b>\n"
        f"section: <code>{_esc(patch['section'])}.{_esc('.'.join(patch['path']))}</code>\n"
        f"action:  <code>{_esc(patch['action'])}</code>\n"
        f"old: <code>{_esc(str(patch.get('old_value')))}</code>\n"
        f"new: <code>{_esc(str(patch.get('new_value')))}</code>\n\n"
        f"<i>{_esc(summary)}</i>"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✓ Confirm", "callback_data": "patch:confirm"},
            {"text": "✗ Cancel",  "callback_data": "patch:cancel"},
        ]],
    }
    notifier.send_telegram(body, chat_id=chat_id, reply_markup=keyboard)


def _handle_callback(cb: dict) -> None:
    data = cb.get("data", "")
    chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
    cb_id = cb.get("id", "")
    sender = _resolve_sender(chat_id, cb.get("message") or {})

    if not data.startswith("patch:"):
        notifier.answer_callback(cb_id, "Unknown action")
        return

    action = data.split(":", 1)[1]
    patch = _PENDING_PATCHES.pop(chat_id, None)
    if not patch:
        notifier.answer_callback(cb_id, "No pending edit")
        notifier.send_telegram("Nothing to apply — pending edit expired.", chat_id=chat_id)
        return

    if action == "cancel":
        notifier.answer_callback(cb_id, "Cancelled")
        notifier.send_telegram("✗ Cancelled.", chat_id=chat_id)
        return

    if action == "confirm":
        if not sender["is_ceo"]:
            notifier.answer_callback(cb_id, "Not authorized")
            notifier.send_telegram("Only CEO can confirm edits.", chat_id=chat_id)
            return
        by = f"CEO:{sender['person_name']}" if sender["person_name"] else "CEO:admin"
        ok, msg = config_patch.apply_patch(patch, by=by)
        notifier.answer_callback(cb_id, "Applied" if ok else "Failed")
        notifier.send_telegram(f"{'✔' if ok else '✗'} {_esc(msg)}", chat_id=chat_id)
        # Reload config so live process sees the change
        try:
            import yaml as _yaml
            new_data = _yaml.safe_load(open(config_patch.CONFIG_PATH))
            if isinstance(new_data, dict):
                config.COMPANY.clear()
                config.COMPANY.update(new_data)
        except Exception as e:
            log.warning("config_reload_failed", extra={"error": str(e)})


# ---------------------------------------------------------------------------
def _esc(s: Any) -> str:
    """HTML-escape for Telegram parse_mode=HTML."""
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
