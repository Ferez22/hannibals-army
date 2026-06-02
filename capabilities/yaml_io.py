"""Atomic YAML read/write. Used by CARTOGRAPHER + DONNA to update company-config.yml."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

EDIT_HISTORY_CAP = 100


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def append_edit_history(
    data: dict[str, Any],
    *,
    by: str,
    action: str,
    sections: list[str] | None = None,
    path_keys: list[str] | None = None,
    from_value: Any = None,
    to_value: Any = None,
    cap: int = EDIT_HISTORY_CAP,
) -> None:
    """Append an entry into data['_meta']['edit_history']. Mutates data in place.

    Use this just before write_yaml_atomic to keep audit trail in sync.
    """
    meta = data.setdefault("_meta", {})
    history = meta.setdefault("edit_history", [])
    entry: dict[str, Any] = {
        "ts": datetime.now().isoformat(),
        "by": by,
        "action": action,
    }
    if sections:
        entry["sections"] = sections
    if path_keys:
        entry["path"] = ".".join(path_keys)
        entry["from"] = from_value
        entry["to"] = to_value
    history.append(entry)
    # cap from the front so newest stay at the end
    if len(history) > cap:
        del history[: len(history) - cap]
    meta["last_updated_by"] = by
    meta["last_updated_at"] = entry["ts"]


def write_yaml_atomic(path: Path, data: dict[str, Any]) -> None:
    """Write to a temp file in the same dir, fsync, then os.replace.

    Prevents corruption from mid-write crashes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
