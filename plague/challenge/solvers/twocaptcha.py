"""2Captcha provider (https://2captcha.com)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .base import SolveResult, SolveTask, Solver, SolverError

log = logging.getLogger("plague.solver.twocaptcha")

IN = "https://2captcha.com/in.php"
RES = "https://2captcha.com/res.php"
COST = 0.003


class TwoCaptcha(Solver):
    name = "2captcha"

    def __init__(
        self,
        api_key: str,
        *,
        timeout_s: int = 180,
        poll_interval_s: float = 5.0,
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

    def _params(self, task: SolveTask) -> dict[str, Any]:
        if not task.sitekey:
            raise SolverError("sitekey is required for 2Captcha")
        base = {
            "key": self.api_key,
            "pageurl": task.page_url,
            "json": 1,
        }
        if task.vendor == "recaptcha":
            return {**base, "method": "userrecaptcha", "googlekey": task.sitekey}
        if task.vendor == "hcaptcha":
            return {**base, "method": "hcaptcha", "sitekey": task.sitekey}
        if task.vendor == "cloudflare_turnstile":
            params = {**base, "method": "turnstile", "sitekey": task.sitekey}
            if task.action:
                params["action"] = task.action
            if task.cdata:
                params["data"] = task.cdata
            return params
        raise SolverError(f"2captcha does not support vendor {task.vendor!r}")

    async def solve(self, task: SolveTask) -> SolveResult:
        params = self._params(task)
        created = await self._get(IN, params)
        if created.get("status") != 1:
            raise SolverError(f"2captcha in.php failed: {created}")
        task_id = str(created.get("request"))
        params = {
            "key": self.api_key,
            "action": "get",
            "id": task_id,
            "json": 1,
        }

        deadline = asyncio.get_running_loop().time() + self.timeout_s
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(self.poll_interval_s)
            result = await self._get(RES, params)
            if result.get("status") == 1:
                return SolveResult(
                    token=str(result.get("request")),
                    provider=self.name,
                    cost_usd=COST,
                    task_id=task_id,
                )
            message = str(result.get("request", ""))
            if message != "CAPCHA_NOT_READY":
                raise SolverError(f"2captcha error: {message}")
        raise SolverError(f"2captcha timed out after {self.timeout_s}s")

    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        try:
            return response.json()
        except Exception as exc:
            raise SolverError(f"2captcha returned non-JSON: {response.text[:200]}") from exc
