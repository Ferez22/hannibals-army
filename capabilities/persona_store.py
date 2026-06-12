"""Persona file IO — atomic per-Person YAML cards.

Each file lives at `config.PERSONA_DIR / <person_id>.yml` and is the single
source of truth for the "magic memory" SCRIBE maintains. Inject this into
ORACLE prompts so the bot greets a user already knowing what they care about.

Schema is loosely typed — sections are append-only. SCRIBE owns the writes;
other agents read via `load_persona()`.

Atomicity: writes go to a temp file beside the target, then `os.replace()`
swaps it in. Reads + writes never see a torn file.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

import config

log = logging.getLogger("hannibal.persona")

# Cap each list section so prompts stay bounded
SECTION_CAPS = {
    "working_on":         8,
    "colleagues_close":   8,
    "recent_decisions":   8,
    "communication_style": 5,
    "preferences":         5,
}


def persona_path(person_id: str) -> Path:
    return config.PERSONA_DIR / f"{person_id}.yml"


def load_persona(person_id: str) -> dict[str, Any] | None:
    """Return parsed persona dict, or None when no file exists (or unreadable)."""
    p = persona_path(person_id)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            log.warning("persona_not_dict", extra={"path": str(p)})
            return None
        return data
    except Exception as e:
        log.warning("persona_load_failed", extra={"path": str(p), "error": str(e)})
        return None


def save_persona(person_id: str, data: dict[str, Any], *, by: str = "SCRIBE") -> None:
    """Atomic write. Caps list sections + stamps `_meta`."""
    config.PERSONA_DIR.mkdir(parents=True, exist_ok=True)
    capped = _apply_caps(data)
    capped["person_id"] = person_id
    meta = capped.setdefault("_meta", {})
    meta["last_updated_at"] = datetime.now().isoformat(timespec="seconds")
    meta["updated_by"] = by

    target = persona_path(person_id)
    tmp = target.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(capped, f, sort_keys=False, allow_unicode=True, width=4096)
    os.replace(tmp, target)
    log.info("persona_saved", extra={"person_id": person_id, "path": str(target)})


def delete_persona(person_id: str) -> bool:
    """Remove file. Returns True when something was deleted."""
    p = persona_path(person_id)
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except Exception as e:
        log.warning("persona_delete_failed", extra={"path": str(p), "error": str(e)})
        return False


def list_personas() -> list[str]:
    """Return all person_ids that have a persona file."""
    if not config.PERSONA_DIR.exists():
        return []
    return sorted(p.stem for p in config.PERSONA_DIR.glob("*.yml"))


# ---------------------------------------------------------------------------
def _apply_caps(data: dict[str, Any]) -> dict[str, Any]:
    """Truncate list sections to their cap. Mutates a copy; original untouched."""
    out = dict(data)
    for key, cap in SECTION_CAPS.items():
        items = out.get(key)
        if isinstance(items, list) and len(items) > cap:
            out[key] = items[:cap]
    return out


def render_persona_for_prompt(data: dict[str, Any] | None) -> str:
    """Render persona as a compact human-readable block for ORACLE synth.
    Returns empty string when no persona to inject."""
    if not data:
        return ""
    name = (data.get("identity") or {}).get("name") or data.get("name") or "?"
    role = (data.get("identity") or {}).get("role") or ""
    tier = (data.get("identity") or {}).get("tier") or ""
    dept = (data.get("identity") or {}).get("department") or ""
    lines = [f"PERSONA: {name}"]
    if role or tier or dept:
        bits = [b for b in (role, dept, f"tier={tier}" if tier else "") if b]
        lines.append("  " + " · ".join(bits))

    def _bullets(label: str, key: str, fmt) -> None:
        items = data.get(key) or []
        if not items:
            return
        lines.append(f"  {label}:")
        for it in items:
            try:
                lines.append(f"    - {fmt(it)}")
            except Exception:
                lines.append(f"    - {it}")

    _bullets("works on",
             "working_on",
             lambda i: f"{i.get('project') or i}" + (f" ({i.get('role')})" if isinstance(i, dict) and i.get('role') else ""))
    _bullets("colleagues",
             "colleagues_close",
             lambda i: f"{i.get('name') or i}" + (f" — {i.get('relation')}" if isinstance(i, dict) and i.get('relation') else ""))
    _bullets("recent decisions",
             "recent_decisions",
             lambda i: f"{i.get('date', '?')}: {i.get('event') or i}")
    style = data.get("communication_style") or []
    if style:
        lines.append("  style: " + "; ".join(style))
    notes = data.get("notes")
    if notes:
        lines.append("  notes: " + str(notes)[:200])
    return "\n".join(lines)
