"""Core data types shared by engines, the router, and the challenge layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Tier(str, Enum):
    """How much browser the caller is willing to pay for."""

    AUTO = "auto"
    FAST = "fast"
    STEALTH = "stealth"
    CHROME = "chrome"


class ChallengeKind(str, Enum):
    """What kind of wall the page is showing."""

    NONE = "none"
    TOKEN = "token"
    RISK = "risk"
    JS = "js"
    UNKNOWN = "unknown"


class Capability(str, Enum):
    """Engine features the router can require."""

    VISUAL = "visual"
    PDF = "pdf"
    VIDEO = "video"
    TRACING = "tracing"
    EXTENSIONS = "extensions"
    DOWNLOADS = "downloads"
    ROUTES = "routes"
    STORAGE_STATE = "storage_state"
    COOKIES = "cookies"
    INIT_SCRIPT = "init_script"


@dataclass(frozen=True)
class EngineInfo:
    name: str
    capabilities: frozenset[Capability]
    description: str

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class Challenge:
    vendor: str
    kind: ChallengeKind
    blocking: bool
    confidence: float
    evidence: tuple[str, ...] = ()
    solvable: bool = False
    sitekey: str | None = None

    @property
    def label(self) -> str:
        return f"{self.vendor}:{self.kind.value}"


@dataclass
class Attempt:
    engine: str
    ok: bool
    elapsed_ms: int
    status: int | None = None
    challenge: str | None = None
    solved: bool = False
    solver: str | None = None
    cost_usd: float = 0.0
    error: str | None = None
    skipped: str | None = None


@dataclass
class Result:
    url: str
    final_url: str
    status: int | None
    title: str
    html: str
    text: str
    engine: str | None
    attempts: list[Attempt] = field(default_factory=list)
    challenge: Challenge | None = None
    solved: bool = False
    elapsed_ms: int = 0
    screenshot: str | None = None
    cookies: list[dict[str, Any]] | None = None

    @property
    def ok(self) -> bool:
        return self.engine is not None and self.status is not None and self.status < 400


@dataclass
class Profile:
    """Per-session browser identity and connection settings."""

    proxy: str | None = None
    locale: str = "en-US"
    timezone: str | None = None
    headless: bool = True
    humanize: bool = True
    user_agent: str | None = None
    storage_state: str | dict[str, Any] | None = None
    user_data_dir: str | None = None
    viewport: dict[str, int] | None = None
    extra_headers: dict[str, str] | None = None
    geoip: bool = False
    human_preset: str = "default"


@dataclass
class Action:
    """A single interaction to run before extracting the page."""

    type: str
    selector: str | None = None
    value: str | None = None
    timeout_ms: int | None = None
