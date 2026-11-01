"""Solver factory."""

from __future__ import annotations

from ...config import Config
from .base import SolveResult, SolveTask, Solver, SolverError
from .capsolver import CapSolver
from .manual import ManualSolver
from .twocaptcha import TwoCaptcha

__all__ = [
    "CapSolver",
    "ManualSolver",
    "SolveResult",
    "SolveTask",
    "Solver",
    "SolverError",
    "TwoCaptcha",
    "build_solver",
]


def build_solver(config: Config) -> Solver | None:
    name = (config.solver or "auto").strip().lower()
    if name in {"none", "off", "disabled", "no"}:
        return None
    if name == "manual":
        return ManualSolver(timeout_s=config.manual_timeout_s)
    if name in {"capsolver", "cap"}:
        if not config.capsolver_key:
            raise SolverError("CAPSOLVER_API_KEY is not set")
        return CapSolver(
            config.capsolver_key, timeout_s=config.solver_timeout_s
        )
    if name in {"2captcha", "twocaptcha", "two"}:
        if not config.twocaptcha_key:
            raise SolverError("TWOCAPTCHA_API_KEY is not set")
        return TwoCaptcha(
            config.twocaptcha_key, timeout_s=config.solver_timeout_s
        )
    if name == "auto":
        if config.capsolver_key:
            return CapSolver(
                config.capsolver_key, timeout_s=config.solver_timeout_s
            )
        if config.twocaptcha_key:
            return TwoCaptcha(
                config.twocaptcha_key, timeout_s=config.solver_timeout_s
            )
        return None
    raise SolverError(f"unknown solver {name!r}")
