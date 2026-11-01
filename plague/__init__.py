"""Plague: tiered browser orchestration.

Cheap Lightpanda pass first, stealth CloakBrowser when a wall appears, and
stock Chrome when you need a reference browser or visual output.
"""

from __future__ import annotations

from .challenge import detect, find_sitekey, inject_token
from .config import Config
from .models import (
    Action,
    Attempt,
    Capability,
    Challenge,
    ChallengeKind,
    EngineInfo,
    Profile,
    Result,
    Tier,
)
from .router import Plague, PlagueError, Probe
from .text import html_to_text

__version__ = "0.1.0"

__all__ = [
    "Action",
    "Attempt",
    "Capability",
    "Challenge",
    "ChallengeKind",
    "Config",
    "EngineInfo",
    "Plague",
    "PlagueError",
    "Probe",
    "Profile",
    "Result",
    "Tier",
    "__version__",
    "detect",
    "find_sitekey",
    "html_to_text",
    "inject_token",
]
