"""CEO-driven natural-language → YAML patch for company-config.yml.

Pipeline:
  free-text instruction → LLM proposes structured patch → CEO confirms → apply.

Patch shape (LLM JSON output):
  {
    "section": "identity",
    "path":    ["hq"],
    "action":  "set",
    "old_value": "<current — informational>",
    "new_value": "Immeuble Mazars, 1 Rue du Lac Ghar el Melh, La Marsa Tunis",
    "human_summary": "Set identity.hq to the full Mazars address"
  }
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import config
from capabilities import llm, yaml_io

log = logging.getLogger("hannibal.config_patch")

CONFIG_PATH = config.REPO_ROOT / "company-config.yml"

# Sections the LLM is allowed to patch
ALLOWED_SECTIONS = {"identity", "leadership", "tools", "culture"}

# Allowed actions
ALLOWED_ACTIONS = {"set", "append", "remove"}


_PROPOSAL_PROMPT = """You translate a CEO instruction into a JSON patch for the company configuration file.

Current company-config.yml (relevant sections only):
__CURRENT_STATE__

The CEO said:
"__INSTRUCTION__"

Output ONLY valid JSON in this exact shape:
{
  "section": "identity | leadership | tools | culture",
  "path":    [<list of keys nested under section, e.g. ["hq"] or ["ceo", "email"]>],
  "action":  "set | append | remove",
  "old_value": <current value if known, else null>,
  "new_value": <new value — string, list, or dict as appropriate>,
  "human_summary": "<one sentence describing the change>"
}

Rules:
- Only edit allowed sections: identity, leadership, tools, culture.
- `set` overwrites; `append` adds to a list; `remove` deletes a key or list item.
- `path` must be a list of strings, even if length 1.
- If the instruction is unclear or outside scope, output: {"error": "<reason>"}

JSON:"""


def propose_patch(instruction: str) -> dict[str, Any] | None:
    """Ask LLM to translate instruction → JSON patch. Returns None on failure."""
    current = yaml_io.read_yaml(CONFIG_PATH) or {}
    snapshot = {k: current.get(k, {}) for k in ALLOWED_SECTIONS}
    current_text = json.dumps(snapshot, indent=2, ensure_ascii=False)

    raw = llm.generate(
        model="openai" if llm.openai_available() else config.MASTER_MODEL,
        prompt=_PROPOSAL_PROMPT.replace("__CURRENT_STATE__", current_text)
                              .replace("__INSTRUCTION__", instruction),
        json_mode=True,
        temperature=0.0,
    )
    parsed = llm.parse_json(raw)
    if not parsed:
        log.warning("patch_propose_no_json", extra={"instruction": instruction[:80]})
        return None
    if "error" in parsed:
        log.info("patch_propose_rejected", extra={"reason": parsed["error"]})
        return {"error": parsed["error"]}

    if not _validate(parsed):
        log.warning("patch_propose_invalid", extra={"parsed": parsed})
        return None
    return parsed


def _validate(p: dict) -> bool:
    if p.get("section") not in ALLOWED_SECTIONS:
        return False
    if p.get("action") not in ALLOWED_ACTIONS:
        return False
    path = p.get("path")
    if not isinstance(path, list) or not all(isinstance(k, str) for k in path):
        return False
    if "new_value" not in p and p.get("action") != "remove":
        return False
    return True


def apply_patch(patch: dict[str, Any], by: str = "CEO") -> tuple[bool, str]:
    """Apply patch atomically + record in edit_history.

    Returns (success, message).
    """
    data = yaml_io.read_yaml(CONFIG_PATH)
    if not isinstance(data, dict):
        data = {}

    section = patch["section"]
    path = patch["path"]
    action = patch["action"]

    target = data.setdefault(section, {})
    if not isinstance(target, dict):
        return False, f"section '{section}' is not a dict — refusing to edit"

    # Walk to parent
    parent = target
    for key in path[:-1]:
        parent = parent.setdefault(key, {})
        if not isinstance(parent, dict):
            return False, f"path '{'.'.join(path[:-1])}' is not a dict"

    leaf = path[-1]
    old_value = parent.get(leaf)

    if action == "set":
        parent[leaf] = patch["new_value"]
    elif action == "append":
        if leaf not in parent or not isinstance(parent[leaf], list):
            parent[leaf] = []
        new_v = patch["new_value"]
        if isinstance(new_v, list):
            parent[leaf].extend(new_v)
        else:
            parent[leaf].append(new_v)
    elif action == "remove":
        if leaf in parent:
            del parent[leaf]

    # Audit
    yaml_io.append_edit_history(
        data,
        by=by,
        action=f"edit:{action}",
        path_keys=[section, *path],
        from_value=old_value,
        to_value=patch.get("new_value"),
    )
    yaml_io.write_yaml_atomic(CONFIG_PATH, data)
    return True, f"applied {action} on {section}.{'.'.join(path)}"
