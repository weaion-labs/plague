"""Named storage states for reusing an authenticated session.

A storage state contains live cookies and localStorage values. Files are written
with owner-only permissions under the Plague cache directory, which is ignored by
git, and they should still be treated as secrets.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .config import project_cache_dir

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class StorageError(RuntimeError):
    """A storage state is missing, invalid, or cannot be written."""


def states_dir() -> Path:
    return project_cache_dir() / "sessions"


def _path(name: str) -> Path:
    if not NAME_PATTERN.match(name or ""):
        raise StorageError(
            "storage name must match [a-z0-9][a-z0-9_-]{0,63}"
        )
    return states_dir() / f"{name}.json"


def save(name: str, state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise StorageError("storage state must be an object")
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "saved": int(time.time()), "state": state}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    try:
        os.chmod(temporary, 0o600)
    except Exception:
        pass
    temporary.replace(path)
    cookies = state.get("cookies") or []
    origins = state.get("origins") or []
    return {
        "name": name,
        "path": str(path),
        "cookies": len(cookies),
        "origins": len(origins),
        "warning": "storage state contains live cookies; keep it private",
    }


def load(name: str) -> dict[str, Any]:
    path = _path(name)
    if not path.is_file():
        raise StorageError(f"storage state not found: {name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise StorageError(f"storage state is not valid JSON: {name}") from exc
    state = data.get("state") if isinstance(data, dict) else None
    if not isinstance(state, dict):
        raise StorageError(f"storage state is malformed: {name}")
    return state


def listing() -> list[dict[str, Any]]:
    directory = states_dir()
    if not directory.is_dir():
        return []
    rows = []
    for path in sorted(directory.glob("*.json")):
        cookies = None
        origins = None
        saved = None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            state = data.get("state") or {}
            cookies = len(state.get("cookies") or [])
            origins = len(state.get("origins") or [])
            saved = data.get("saved")
        except Exception:
            pass
        rows.append(
            {
                "name": path.stem,
                "cookies": cookies,
                "origins": origins,
                "saved": saved,
            }
        )
    return rows


def delete(name: str) -> bool:
    path = _path(name)
    if not path.is_file():
        return False
    path.unlink()
    return True
