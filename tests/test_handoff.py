from __future__ import annotations

import asyncio

import pytest

from plague.config import Config
from plague.handoff import (
    HandoffError,
    HandoffManager,
    HandoffState,
    _display_mode,
    _free_port,
    _normalize_cdp,
    _ozone_args,
    _proxy_arg,
)


def test_proxy_arg_keeps_host_and_port():
    flag, note = _proxy_arg("http://user:pass@127.0.0.1:8080")
    assert flag == "--proxy-server=http://127.0.0.1:8080"
    assert note and "credentials" in note


def test_proxy_arg_rejects_missing_host():
    flag, note = _proxy_arg("://bad")
    assert flag is None
    assert note


def test_free_port_is_usable():
    port = _free_port()
    assert 0 < port < 65536


def test_handoff_manager_starts_idle():
    manager = HandoffManager(Config())
    assert manager.running is False
    assert manager.describe() == {"running": False}


def test_config_reads_domain_lists(monkeypatch):
    monkeypatch.setenv(
        "PLAGUE_ALLOWED_DOMAINS", "Example.com, sub.example.org"
    )
    monkeypatch.setenv("PLAGUE_SOLVE_DOMAINS", "example.com")
    config = Config.from_env()
    assert config.allowed_domains == ["example.com", "sub.example.org"]
    assert config.solve_domains == ["example.com"]


def test_display_mode_is_native_off_linux(monkeypatch):
    monkeypatch.setattr("plague.handoff.sys.platform", "darwin")
    assert _display_mode() == "native"


def test_display_mode_reads_wayland_and_x11(monkeypatch):
    monkeypatch.setattr("plague.handoff.sys.platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert _display_mode() is None

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    assert _display_mode() == "wayland"

    monkeypatch.setenv("DISPLAY", ":0")
    assert _display_mode() == "both"


def test_ozone_flags_follow_display():
    assert _ozone_args("auto", "wayland") == ["--ozone-platform=wayland"]
    assert _ozone_args("auto", "both") == ["--ozone-platform-hint=auto"]
    assert _ozone_args("x11", "wayland") == ["--ozone-platform=x11"]
    assert _ozone_args("wayland", "x11") == ["--ozone-platform=wayland"]
    assert _ozone_args("auto", "native") == []


def test_cdp_url_normalization_and_attached_state():
    assert _normalize_cdp("127.0.0.1:9222") == "http://127.0.0.1:9222"
    assert _normalize_cdp("http://host:9222/") == "http://host:9222"

    state = HandoffState(
        process=None,
        port=0,
        profile_dir="",
        attached=True,
        cdp_override="wss://browser.example/cdp",
    )
    assert state.cdp_url == "wss://browser.example/cdp"


def test_attach_rejects_empty_url():
    manager = HandoffManager(Config())
    with pytest.raises(HandoffError):
        asyncio.run(manager.attach(""))
