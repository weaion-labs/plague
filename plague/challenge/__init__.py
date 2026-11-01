"""Challenge detection, token injection, and solver providers."""

from .detect import BLOCK_STATUSES, SIGNATURES, detect, find_sitekey
from .inject import FIELDS, inject_token, wait_for_token
from .actions import click_turnstile
from .solvers import (
    CapSolver,
    ManualSolver,
    SolveResult,
    SolveTask,
    Solver,
    SolverError,
    TwoCaptcha,
    build_solver,
)

__all__ = [
    "BLOCK_STATUSES",
    "SIGNATURES",
    "CapSolver",
    "FIELDS",
    "ManualSolver",
    "SolveResult",
    "SolveTask",
    "Solver",
    "SolverError",
    "TwoCaptcha",
    "build_solver",
    "click_turnstile",
    "detect",
    "find_sitekey",
    "inject_token",
    "wait_for_token",
]
