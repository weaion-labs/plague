"""Environment-driven configuration and binary discovery."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .models import Profile


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def project_cache_dir() -> Path:
    """Prefer ./.plague when it already exists, else ~/.cache/plague.

    PLAGUE_HOME always wins. This keeps an installed package from dropping
    binaries into whatever directory the user happens to be in.
    """
    override = os.environ.get("PLAGUE_HOME")
    if override:
        return Path(override).expanduser()
    local = Path.cwd() / ".plague"
    if local.is_dir():
        return local
    return Path.home() / ".cache" / "plague"


def find_lightpanda() -> str | None:
    explicit = os.environ.get("PLAGUE_LIGHTPANDA_BIN")
    if explicit:
        path = Path(explicit).expanduser()
        return str(path) if path.is_file() else None

    found = shutil.which("lightpanda")
    if found:
        return found

    candidates = [
        project_cache_dir() / "bin" / "lightpanda",
        Path.cwd() / ".plague" / "bin" / "lightpanda",
        Path.home() / ".cache" / "plague" / "bin" / "lightpanda",
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def find_chrome() -> str | None:
    explicit = os.environ.get("PLAGUE_CHROME_EXECUTABLE")
    if explicit:
        path = Path(explicit).expanduser()
        return str(path) if path.is_file() else None

    names = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
    ]
    for name in names:
        found = shutil.which(name)
        if found:
            return found

    mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if mac.is_file():
        return str(mac)
    return None


@dataclass
class Config:
    # Engines
    lightpanda_bin: str | None = field(default_factory=find_lightpanda)
    lightpanda_port: int = 0  # 0 means pick a free port per session
    chrome_executable: str | None = field(default_factory=find_chrome)
    chrome_channel: str | None = None
    cloak_license_key: str | None = None

    # Browser defaults
    headless: bool = True
    humanize: bool = True
    proxy: str | None = None
    locale: str = "en-US"
    timezone: str | None = None
    timeout_ms: int = 30_000
    user_data_dir: str | None = None

    # Challenge handling
    solver: str = "auto"  # auto | none | capsolver | 2captcha | manual
    capsolver_key: str | None = None
    twocaptcha_key: str | None = None
    solver_timeout_s: int = 180
    manual_timeout_s: int = 300
    solve_on_fast: bool = False
    js_challenge_rounds: int = 3
    js_challenge_wait_ms: int = 2500

    # Behavior
    max_escalations: int = 3
    evidence_limit: int = 500

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            lightpanda_bin=find_lightpanda(),
            lightpanda_port=_env_int("PLAGUE_LIGHTPANDA_PORT", 0),
            chrome_executable=find_chrome(),
            chrome_channel=os.environ.get("PLAGUE_CHROME_CHANNEL") or None,
            cloak_license_key=os.environ.get("PLAGUE_CLOAK_LICENSE_KEY")
            or os.environ.get("CLOAKBROWSER_LICENSE_KEY")
            or None,
            headless=_env_bool("PLAGUE_HEADLESS", True),
            humanize=_env_bool("PLAGUE_HUMANIZE", True),
            proxy=os.environ.get("PLAGUE_PROXY") or None,
            locale=os.environ.get("PLAGUE_LOCALE", "en-US"),
            timezone=os.environ.get("PLAGUE_TIMEZONE") or None,
            timeout_ms=_env_int("PLAGUE_TIMEOUT_MS", 30_000),
            user_data_dir=os.environ.get("PLAGUE_PROFILE_DIR") or None,
            solver=os.environ.get("PLAGUE_SOLVER", "auto"),
            capsolver_key=os.environ.get("CAPSOLVER_API_KEY") or None,
            twocaptcha_key=os.environ.get("TWOCAPTCHA_API_KEY") or None,
            solver_timeout_s=_env_int("PLAGUE_SOLVER_TIMEOUT_S", 180),
            manual_timeout_s=_env_int("PLAGUE_MANUAL_TIMEOUT_S", 300),
            solve_on_fast=_env_bool("PLAGUE_SOLVE_ON_FAST", False),
            js_challenge_rounds=_env_int("PLAGUE_JS_ROUNDS", 3),
            js_challenge_wait_ms=_env_int("PLAGUE_JS_WAIT_MS", 2500),
        )

    def profile(self, **overrides) -> Profile:
        values = {
            "proxy": self.proxy,
            "locale": self.locale,
            "timezone": self.timezone,
            "headless": self.headless,
            "humanize": self.humanize,
            "user_data_dir": self.user_data_dir,
        }
        values.update({k: v for k, v in overrides.items() if v is not None})
        return Profile(**values)
