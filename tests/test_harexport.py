from __future__ import annotations

import asyncio
import json
import stat
from dataclasses import dataclass, field

from plague.harexport import build_har, curl_commands, write_export
from plague.observe import Observer


@dataclass
class FakeRequest:
    method: str = "POST"
    url: str = "https://example.com/api?x=1&x=2"
    resource_type: str = "fetch"
    headers: dict = field(
        default_factory=lambda: {
            "cookie": "a=1; b=2",
            "content-type": "application/json",
            "authorization": "Bearer token",
        }
    )
    post_data: str | None = '{"role":"admin"}'
    failure: str | None = None


@dataclass
class FakeResponse:
    request: FakeRequest
    status: int = 201
    ok: bool = True
    status_text: str = "Created"
    headers: dict = field(
        default_factory=lambda: {
            "content-type": "application/json",
            "set-cookie": "x=1; Path=/",
        }
    )

    async def text(self) -> str:
        return '{"ok":true}'


def _observer():
    observer = Observer()
    request = FakeRequest()
    observer._on_request(request)
    observer._on_response(FakeResponse(request=request))
    return observer


def test_build_har_shape_and_body():
    har = asyncio.run(build_har(_observer()))
    entry = har["log"]["entries"][0]
    assert har["log"]["version"] == "1.2"
    assert entry["request"]["method"] == "POST"
    assert entry["request"]["queryString"] == [
        {"name": "x", "value": "1"},
        {"name": "x", "value": "2"},
    ]
    assert entry["request"]["cookies"] == [
        {"name": "a", "value": "1"},
        {"name": "b", "value": "2"},
    ]
    assert entry["request"]["postData"]["text"] == '{"role":"admin"}'
    assert entry["request"]["postData"]["mimeType"] == "application/json"
    assert entry["response"]["status"] == 201
    assert entry["response"]["content"]["text"] == '{"ok":true}'
    assert entry["_resourceType"] == "fetch"


def test_curl_commands_include_headers_and_body():
    commands = curl_commands(_observer())
    assert len(commands) == 1
    command = commands[0]
    assert "curl" in command
    assert "example.com/api" in command
    assert "authorization: Bearer token" in command
    assert "--data-raw" in command


def test_write_export_is_owner_only(tmp_path):
    path = write_export(tmp_path / "har.json", json.dumps({"ok": True}))
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
