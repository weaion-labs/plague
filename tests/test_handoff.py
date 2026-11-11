from __future__ import annotations

from plague.config import Config
from plague.handoff import HandoffManager, _free_port, _proxy_arg


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
