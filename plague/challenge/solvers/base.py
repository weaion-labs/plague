"""Solver interface for token-based challenges."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class SolverError(RuntimeError):
    pass


@dataclass
class SolveTask:
    vendor: str
    page_url: str
    sitekey: str
    page: Any | None = None
    html: str = ""
    action: str | None = None
    cdata: str | None = None


@dataclass
class SolveResult:
    token: str
    provider: str
    cost_usd: float = 0.0
    task_id: str | None = None


class Solver(ABC):
    name: str = "solver"

    @abstractmethod
    async def solve(self, task: SolveTask) -> SolveResult:
        """Return a response token for the challenge."""

    async def close(self) -> None:
        return None
