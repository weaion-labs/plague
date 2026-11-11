from __future__ import annotations

import pytest

from plague.recipes import (
    RecipeError,
    delete,
    listing,
    load,
    recipes_dir,
    save,
)


def test_recipe_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAGUE_HOME", str(tmp_path))
    saved = save(
        "login",
        [
            {"type": "fill", "ref": "e1", "value": "me@example.com"},
            {"type": "click", "ref": "e2"},
        ],
    )
    assert saved["name"] == "login"
    assert saved["actions"] == 2
    assert recipes_dir().is_dir()

    actions = load("login")
    assert [action.type for action in actions] == ["fill", "click"]
    assert actions[0].ref == "e1"
    assert actions[0].value == "me@example.com"

    rows = listing()
    assert len(rows) == 1
    assert rows[0]["name"] == "login"
    assert rows[0]["actions"] == 2

    assert delete("login") is True
    with pytest.raises(RecipeError):
        load("login")


def test_recipe_rejects_bad_names_and_empty_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAGUE_HOME", str(tmp_path))
    with pytest.raises(RecipeError):
        save("../escape", [{"type": "click", "ref": "e1"}])
    with pytest.raises(RecipeError):
        save("ok", [])
    with pytest.raises(RecipeError):
        load("missing")
