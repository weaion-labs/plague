from __future__ import annotations

import asyncio

import pytest

from plague.interact import (
    ActionError,
    parse_actions,
    run_actions,
    selector_for,
)
from plague.models import Action
from plague.snapshot import _snapshot_js, collect


def test_parse_actions_accepts_dicts_and_refs():
    parsed = parse_actions(
        [
            {"type": "click", "ref": "@e3"},
            {"type": "fill", "ref": "e4", "value": "hello"},
            {"type": "wait", "value": 500},
        ]
    )
    assert [action.type for action in parsed] == ["click", "fill", "wait"]
    assert selector_for(parsed[0]) == '[data-plague-ref="e3"]'
    assert selector_for(parsed[1]) == '[data-plague-ref="e4"]'
    assert parsed[2].value == "500"


def test_parse_actions_rejects_unknown_type_and_fields():
    with pytest.raises(ActionError):
        parse_actions([{"type": "teleport", "ref": "e1"}])
    with pytest.raises(ActionError):
        parse_actions([{"type": "click", "ref": "e1", "colour": "red"}])


def test_selector_for_requires_a_target():
    with pytest.raises(ActionError):
        selector_for(Action(type="click"))
    with pytest.raises(ActionError):
        selector_for(Action(type="click", ref="button-3"))


class Recorder:
    def __init__(self):
        self.calls = []

    def supports(self, capability):
        return True

    async def click(self, selector, timeout_ms=None):
        self.calls.append(("click", selector))

    async def fill(self, selector, value, timeout_ms=None):
        self.calls.append(("fill", selector, value))

    async def press(self, selector, key, timeout_ms=None):
        self.calls.append(("press", selector, key))

    async def hover(self, selector, timeout_ms=None):
        self.calls.append(("hover", selector))

    async def select_option(self, selector, value, timeout_ms=None):
        self.calls.append(("select", selector, value))

    async def check(self, selector, timeout_ms=None):
        self.calls.append(("check", selector))

    async def uncheck(self, selector, timeout_ms=None):
        self.calls.append(("uncheck", selector))

    async def set_input_files(self, selector, files, timeout_ms=None):
        self.calls.append(("set_files", selector, files))

    async def wait_for_selector(self, selector, timeout_ms=None):
        self.calls.append(("wait_for", selector))

    async def wait_for_timeout(self, ms):
        self.calls.append(("wait", ms))

    async def exists(self, selector):
        return True

    async def evaluate(self, expression):
        self.calls.append(("evaluate", expression))

    async def back(self):
        self.calls.append(("back",))

    async def goto(self, url, wait_until="domcontentloaded", timeout_ms=None):
        self.calls.append(("goto", url))


def test_run_actions_maps_refs_to_attributes():
    recorder = Recorder()
    actions = parse_actions(
        [
            {"type": "click", "ref": "e1"},
            {"type": "fill", "ref": "e2", "value": "user@example.com"},
            {"type": "press", "ref": "e2", "value": "Enter"},
            {"type": "select", "selector": "#country", "value": "GB"},
            {"type": "check", "selector": "#terms"},
            {"type": "set_files", "ref": "e5", "value": "/tmp/a.txt\n/tmp/b.txt"},
            {"type": "scroll", "value": 400},
            {"type": "back"},
            {"type": "goto", "value": "https://example.com/next"},
        ]
    )
    asyncio.run(run_actions(recorder, actions))

    assert recorder.calls == [
        ("click", '[data-plague-ref="e1"]'),
        ("fill", '[data-plague-ref="e2"]', "user@example.com"),
        ("press", '[data-plague-ref="e2"]', "Enter"),
        ("select", "#country", "GB"),
        ("check", "#terms"),
        ("set_files", '[data-plague-ref="e5"]', ["/tmp/a.txt", "/tmp/b.txt"]),
        ("evaluate", "window.scrollBy(0, 400)"),
        ("back",),
        ("goto", "https://example.com/next"),
    ]


class SnapshotSession:
    class Page:
        url = "https://example.com/"

    def __init__(self):
        self.page = self.Page()

    async def evaluate(self, expression):
        assert "const limit = 12" in expression
        return {
            "url": "https://example.com/",
            "title": "Example",
            "count": 1,
            "truncated": False,
            "elements": [
                {"ref": "e1", "role": "link", "name": "More", "tag": "a"}
            ],
        }

    async def title(self):
        return "Example"


def test_snapshot_js_embeds_limit_and_collect_returns_elements():
    assert "const limit = 7" in _snapshot_js(7)
    data = asyncio.run(collect(SnapshotSession(), limit=12))
    assert data["count"] == 1
    assert data["elements"][0]["ref"] == "e1"
    assert data["url"] == "https://example.com/"
