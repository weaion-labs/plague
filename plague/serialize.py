"""JSON-friendly serialization for CLI output."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import Attempt, Challenge, Result
from .router import PlagueError, Probe


def challenge_dict(challenge: Challenge | None) -> dict[str, Any] | None:
    if challenge is None:
        return None
    return {
        "vendor": challenge.vendor,
        "kind": challenge.kind.value,
        "blocking": challenge.blocking,
        "confidence": challenge.confidence,
        "solvable": challenge.solvable,
        "sitekey": challenge.sitekey,
        "evidence": list(challenge.evidence),
    }


def attempt_dict(attempt: Attempt) -> dict[str, Any]:
    data = asdict(attempt)
    data["cost_usd"] = round(float(data["cost_usd"]), 6)
    return data


def result_dict(result: Result, *, include_html: bool = False) -> dict[str, Any]:
    data = {
        "ok": result.ok,
        "url": result.url,
        "final_url": result.final_url,
        "status": result.status,
        "title": result.title,
        "text": result.text,
        "engine": result.engine,
        "solved": result.solved,
        "elapsed_ms": result.elapsed_ms,
        "screenshot": result.screenshot,
        "cookies": result.cookies,
        "challenge": challenge_dict(result.challenge),
        "attempts": [attempt_dict(a) for a in result.attempts],
    }
    if include_html:
        data["html"] = result.html
    return data


def probe_dict(probe: Probe) -> dict[str, Any]:
    return {
        "url": probe.url,
        "final_url": probe.final_url,
        "status": probe.status,
        "engine": probe.engine,
        "title": probe.title,
        "challenge": challenge_dict(probe.challenge),
        "elapsed_ms": probe.elapsed_ms,
    }


def error_dict(error: PlagueError) -> dict[str, Any]:
    return {
        "ok": False,
        "error": str(error),
        "attempts": [attempt_dict(a) for a in error.attempts],
    }
