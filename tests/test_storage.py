from __future__ import annotations

import json
import stat

import pytest

from plague.storage import (
    StorageError,
    delete,
    listing,
    load,
    save,
    states_dir,
)


def test_storage_round_trip_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAGUE_HOME", str(tmp_path))
    state = {
        "cookies": [{"name": "session", "value": "secret"}],
        "origins": [{"origin": "https://example.com", "localStorage": []}],
    }
    saved = save("target", state)
    assert saved["cookies"] == 1
    assert saved["origins"] == 1
    path = states_dir() / "target.json"
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["state"] == state

    assert load("target") == state
    rows = listing()
    assert rows[0]["name"] == "target"
    assert rows[0]["cookies"] == 1

    assert delete("target") is True
    with pytest.raises(StorageError):
        load("target")


def test_storage_rejects_bad_names(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAGUE_HOME", str(tmp_path))
    with pytest.raises(StorageError):
        save("../escape", {"cookies": []})
    with pytest.raises(StorageError):
        load("missing")
