"""Manual solving: pause on a headed browser and wait for a human."""

from __future__ import annotations

import logging

from .base import SolveResult, SolveTask, Solver, SolverError
from ..inject import wait_for_token

log = logging.getLogger("plague.solver.manual")


class ManualSolver(Solver):
    name = "manual"

    def __init__(self, timeout_s: int = 300) -> None:
        self.timeout_s = timeout_s

    async def solve(self, task: SolveTask) -> SolveResult:
        if task.page is None:
            raise SolverError("manual solving needs a live page")
        log.warning(
            "manual solve required for %s at %s; complete it in the browser window",
            task.vendor,
            task.page_url,
        )
        token = await wait_for_token(
            task.page, task.vendor, timeout_ms=self.timeout_s * 1000
        )
        if not token:
            raise SolverError(
                f"no manual token appeared within {self.timeout_s}s"
            )
        return SolveResult(token=token, provider=self.name, cost_usd=0.0)
