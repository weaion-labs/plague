"""Saved action recipes for repeated flows.

A recipe is the action list that worked, stored as JSON. Replaying it is a
deterministic tool call instead of regenerating a Playwright script, which is
where agents tend to introduce syntax errors and stale selectors.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .config import project_cache_dir
from .interact import parse_actions
from .models import Action

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class RecipeError(RuntimeError):
    """A recipe is missing, invalid, or cannot be stored."""


def recipes_dir() -> Path:
    return project_cache_dir() / "recipes"


def _path(name: str) -> Path:
    if not NAME_PATTERN.match(name or ""):
        raise RecipeError(
            "recipe name must match [a-z0-9][a-z0-9_-]{0,63}"
        )
    return recipes_dir() / f"{name}.json"


def to_dicts(actions: Iterable[Action]) -> list[dict[str, Any]]:
    return [asdict(action) for action in actions]


def save(name: str, actions: Iterable[Action | dict[str, Any]]) -> dict[str, Any]:
    parsed = parse_actions(actions)
    if not parsed:
        raise RecipeError("recipe has no actions")
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name,
        "updated": int(time.time()),
        "actions": to_dicts(parsed),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return {
        "name": name,
        "actions": len(parsed),
        "path": str(path),
    }


def load(name: str) -> list[Action]:
    path = _path(name)
    if not path.is_file():
        raise RecipeError(f"recipe not found: {name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RecipeError(f"recipe is not valid JSON: {name}") from exc
    raw = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise RecipeError(f"recipe has no action list: {name}")
    return parse_actions(raw)


def listing() -> list[dict[str, Any]]:
    directory = recipes_dir()
    if not directory.is_dir():
        return []
    rows = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            count = len(data.get("actions") or [])
            updated = data.get("updated")
        except Exception:
            count = 0
            updated = None
        rows.append(
            {"name": path.stem, "actions": count, "updated": updated}
        )
    return rows


def delete(name: str) -> bool:
    path = _path(name)
    if not path.is_file():
        return False
    path.unlink()
    return True
