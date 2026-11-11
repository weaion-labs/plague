from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from plague.observe import Observer


@dataclass
class FakeRequest:
    method: str = "GET"
    url: str = "https://example.com/"
    resource_type: str = "document"
    failure: str | None = None


@dataclass
class FakeResponse:
    request: FakeRequest
    status: int = 200
    ok: bool = True
    headers: dict[str, str] = field(
        default_factory=lambda: {"content-type": "text/html; charset=utf-8"}
    )

    async def text(self) -> str:
        return "<html>body</html>"


@dataclass
class FakeMessage:
    type: str = "log"
    text: str = "hello"


def test_observer_records_requests_responses_and_logs():
    observer = Observer()
    request = FakeRequest()
    observer._on_request(request)
    observer._on_response(FakeResponse(request=request, status=204, ok=True))
    observer._on_console(FakeMessage())
    observer._on_console(FakeMessage(type="error", text="bad"))
    observer._on_error(RuntimeError("boom"))

    network = asyncio.run(observer.network())
    assert len(network) == 1
    assert network[0]["method"] == "GET"
    assert network[0]["status"] == 204
    assert network[0]["mime"] == "text/html"

    logs = observer.logs()
    assert [item["text"] for item in logs] == ["hello", "bad", "boom"]
    assert logs[-1]["source"] == "page"
    assert observer.logs(level="error")[0]["text"] == "bad"


def test_observer_attaches_response_bodies_on_request():
    observer = Observer()
    request = FakeRequest(url="https://example.com/api")
    observer._on_request(request)
    observer._on_response(
        FakeResponse(
            request=request,
            headers={"content-type": "application/json; charset=utf-8"},
        )
    )
    rows = asyncio.run(observer.network(include_body=True))
    assert rows[0]["body"] == "<html>body</html>"
    plain = asyncio.run(observer.network())
    assert "body" not in plain[0]
    assert "_response" not in plain[0]


def test_observer_filters_and_clears():
    observer = Observer()
    first = FakeRequest(url="https://example.com/api/users")
    second = FakeRequest(url="https://example.com/static/app.js")
    observer._on_request(first)
    observer._on_request(second)

    assert len(asyncio.run(observer.network(filter="api"))) == 1
    observer.clear()
    assert asyncio.run(observer.network()) == []
    assert observer.logs() == []


def test_observer_marks_failed_requests():
    observer = Observer()
    request = FakeRequest(url="https://example.com/broken")
    observer._on_request(request)
    observer._on_failed(request)
    entry = asyncio.run(observer.network())[0]
    assert entry["error"] == "request failed"
