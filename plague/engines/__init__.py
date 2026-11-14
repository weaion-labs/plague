"""Engine registry."""

from __future__ import annotations

from ..config import Config
from .base import (
    BaseEngine,
    CapabilityError,
    EngineError,
    EngineUnavailable,
    Nav,
    Session,
    playwright_proxy,
)
from .chrome import ChromeEngine
from .cloak import CloakEngine
from .lightpanda import LightpandaEngine
from .patchright import PatchrightEngine

__all__ = [
    "BaseEngine",
    "CapabilityError",
    "ChromeEngine",
    "CloakEngine",
    "EngineError",
    "EngineUnavailable",
    "LightpandaEngine",
    "Nav",
    "PatchrightEngine",
    "Session",
    "default_engines",
    "playwright_proxy",
]


def default_engines(config: Config) -> dict[str, BaseEngine]:
    return {
        "lightpanda": LightpandaEngine(config),
        "patchright": PatchrightEngine(config),
        "cloak": CloakEngine(config),
        "chrome": ChromeEngine(config),
    }
