import asyncio
import json

import httpx
import pytest

from plague.challenge.solvers.base import SolveTask, SolverError
from plague.challenge.solvers.capsolver import CapSolver
from plague.challenge.solvers.twocaptcha import TwoCaptcha


def test_capsolver_recaptcha_flow():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/createTask":
            seen["create"] = json.loads(request.content)
            return httpx.Response(200, json={"errorId": 0, "taskId": "t1"})
        if request.url.path == "/getTaskResult":
            return httpx.Response(
                200,
                json={
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"gRecaptchaResponse": "TOKEN"},
                },
            )
        return httpx.Response(404)

    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        solver = CapSolver(
            "secret", timeout_s=5, poll_interval_s=0.01, client=client
        )
        try:
            return await solver.solve(
                SolveTask(
                    vendor="recaptcha",
                    page_url="https://target.test/login",
                    sitekey="SITE_KEY",
                )
            )
        finally:
            await solver.close()

    result = asyncio.run(scenario())
    assert result.token == "TOKEN"
    assert result.provider == "capsolver"
    assert result.cost_usd > 0
    assert seen["create"]["clientKey"] == "secret"
    assert seen["create"]["task"]["type"] == "ReCaptchaV2TaskProxyLess"
    assert seen["create"]["task"]["websiteKey"] == "SITE_KEY"


def test_capsolver_surfaces_api_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "errorId": 1,
                "errorCode": "ERROR_KEY_DENIED_ACCESS",
                "errorDescription": "denied",
            },
        )

    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        solver = CapSolver(
            "bad", timeout_s=5, poll_interval_s=0.01, client=client
        )
        try:
            await solver.solve(
                SolveTask(
                    vendor="hcaptcha",
                    page_url="https://target.test/",
                    sitekey="KEY",
                )
            )
        finally:
            await solver.close()

    with pytest.raises(SolverError, match="ERROR_KEY_DENIED_ACCESS"):
        asyncio.run(scenario())


def test_capsolver_rejects_unsupported_vendor():
    solver = CapSolver("secret", timeout_s=1)
    with pytest.raises(SolverError, match="does not support"):
        asyncio.run(
            solver.solve(
                SolveTask(
                    vendor="datadome",
                    page_url="https://target.test/",
                    sitekey="KEY",
                )
            )
        )


def test_twocaptcha_recaptcha_flow():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/in.php":
            seen["in"] = dict(request.url.params)
            return httpx.Response(200, json={"status": 1, "request": "123"})
        if request.url.path == "/res.php":
            return httpx.Response(200, json={"status": 1, "request": "TOKEN2"})
        return httpx.Response(404)

    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        solver = TwoCaptcha(
            "secret", timeout_s=5, poll_interval_s=0.01, client=client
        )
        try:
            return await solver.solve(
                SolveTask(
                    vendor="recaptcha",
                    page_url="https://target.test/",
                    sitekey="SITE",
                )
            )
        finally:
            await solver.close()

    result = asyncio.run(scenario())
    assert result.token == "TOKEN2"
    assert result.provider == "2captcha"
    assert seen["in"]["method"] == "userrecaptcha"
    assert seen["in"]["googlekey"] == "SITE"


def test_twocaptcha_reports_not_ready_then_token():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/in.php":
            return httpx.Response(200, json={"status": 1, "request": "42"})
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200, json={"status": 0, "request": "CAPCHA_NOT_READY"}
            )
        return httpx.Response(200, json={"status": 1, "request": "LATE"})

    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        solver = TwoCaptcha(
            "secret", timeout_s=5, poll_interval_s=0.01, client=client
        )
        try:
            return await solver.solve(
                SolveTask(
                    vendor="hcaptcha",
                    page_url="https://target.test/",
                    sitekey="SITE",
                )
            )
        finally:
            await solver.close()

    result = asyncio.run(scenario())
    assert result.token == "LATE"
    assert calls["n"] == 2
