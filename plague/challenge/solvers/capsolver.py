"""CapSolver provider (https://capsolver.com)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .base import SolveResult, SolveTask, Solver, SolverError

log = logging.getLogger("plague.solver.capsolver")

API = "https://api.capsolver.com"

# Approximate list prices in USD per solve. Treat as telemetry, not billing.
COSTS = {
    "recaptcha": 0.0008,
    "hcaptcha": 0.0010,
    "cloudflare_turnstile": 0.0015,
}


class CapSolver(Solver):
    name = "capsolver"

    def __init__(
        self,
        api_key: str,
        *,
        timeout_s: int = 180,
        poll_interval_s: float = 3.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _task_payload(self, task: SolveTask) -> dict[str, Any]:
        if not task.sitekey:
            raise SolverError("sitekey is required for CapSolver")
        if task.vendor == "recaptcha":
            enterprise = "recaptcha/enterprise" in task.html.lower()
            return {
                "type": (
                    "ReCaptchaV2EnterpriseTaskProxyLess"
                    if enterprise
                    else "ReCaptchaV2TaskProxyLess"
                ),
                "websiteURL": task.page_url,
                "websiteKey": task.sitekey,
            }
        if task.vendor == "hcaptcha":
            return {
                "type": "HCaptchaTaskProxyLess",
                "websiteURL": task.page_url,
                "websiteKey": task.sitekey,
            }
        if task.vendor == "cloudflare_turnstile":
            payload: dict[str, Any] = {
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": task.page_url,
                "websiteKey": task.sitekey,
            }
            if task.action:
                payload["action"] = task.action
            if task.cdata:
                payload["cdata"] = task.cdata
            return payload
        raise SolverError(f"capsolver does not support vendor {task.vendor!r}")

    async def solve(self, task: SolveTask) -> SolveResult:
        payload = self._task_payload(task)
        created = await self._post(
            "/createTask", {"clientKey": self.api_key, "task": payload}
        )
        task_id = created.get("taskId")
        if not task_id:
            raise SolverError(f"capsolver createTask returned no taskId: {created}")

        deadline = asyncio.get_running_loop().time() + self.timeout_s
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(self.poll_interval_s)
            result = await self._post(
                "/getTaskResult", {"clientKey": self.api_key, "taskId": task_id}
            )
            status = result.get("status")
            if status == "ready":
                solution = result.get("solution") or {}
                token = (
                    solution.get("gRecaptchaResponse")
                    or solution.get("token")
                    or solution.get("hCaptchaResponse")
                )
                if not token:
                    raise SolverError(f"capsolver returned no token: {result}")
                return SolveResult(
                    token=str(token),
                    provider=self.name,
                    cost_usd=COSTS.get(task.vendor, 0.001),
                    task_id=str(task_id),
                )
            if status not in {"processing", "idle"}:
                raise SolverError(f"capsolver status {status}: {result}")
        raise SolverError(f"capsolver timed out after {self.timeout_s}s")

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.post(API + path, json=body)
        response.raise_for_status()
        data = response.json()
        if data.get("errorId"):
            raise SolverError(
                f"capsolver error {data.get('errorCode')}: "
                f"{data.get('errorDescription')}"
            )
        return data
