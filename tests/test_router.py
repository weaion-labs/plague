import asyncio

import pytest

from plague.challenge.solvers.base import SolveResult
from plague.models import Capability, EngineInfo, Tier
from plague.router import Plague, PlagueError
from plague.config import Config

CLEAN_HTML = (
    "<html><head><title>Clean</title></head><body>"
    + "<p>real content</p>" * 400
    + "</body></html>"
)

CF_HTML = """
<html><head><title>Just a moment...</title></head>
<body><script src="/cdn-cgi/challenge-platform/x.js"></script></body></html>
"""

RECAPTCHA_HTML = """
<html><body><form><div class="g-recaptcha" data-sitekey="SITE_KEY"></div></form>
<script src="https://www.google.com/recaptcha/api.js"></script></body></html>
"""

APP_SHELL_HTML = """
<html><body><div id="root"></div><script src="/static/app.js"></script></body></html>
"""


class FakePage:
    def __init__(self):
        self.url = "about:blank"


class FakeSession:
    def __init__(self, pages, info):
        self.pages = list(pages)
        self.info = info
        self.index = 0
        self.page = FakePage()
        self.closed = False

    def supports(self, capability):
        return capability in self.info.capabilities

    async def goto(self, url, wait_until="domcontentloaded", timeout_ms=None):
        from plague.engines.base import Nav

        page = self.pages[min(self.index, len(self.pages) - 1)]
        self.index += 1
        self.page.url = page.get("url", url)
        return Nav(
            url=self.page.url,
            status=page["status"],
            headers=page.get("headers", {}),
        )

    async def content(self):
        return self.pages[min(self.index - 1, len(self.pages) - 1)]["html"]

    async def title(self):
        return "Fake title"

    async def text(self):
        return "fake text"

    async def wait_for_timeout(self, ms):
        return None

    async def screenshot(self, path):
        return path

    async def click(self, selector, timeout_ms=None):
        return None

    async def fill(self, selector, value, timeout_ms=None):
        return None

    async def press(self, selector, key, timeout_ms=None):
        return None

    async def wait_for_selector(self, selector, timeout_ms=None):
        return None

    async def evaluate(self, expression):
        return None

    async def close(self):
        self.closed = True


class FakeEngine:
    def __init__(self, name, pages, caps=()):
        self.info = EngineInfo(
            name=name,
            capabilities=frozenset(caps),
            description="fake engine",
        )
        self.pages = pages
        self.opened = 0

    async def open(self, profile):
        self.opened += 1
        return FakeSession(self.pages, self.info)

    def describe(self):
        return {"name": self.info.name, "available": True}


class FakeSolver:
    name = "fake"

    def __init__(self):
        self.calls = []

    async def solve(self, task):
        self.calls.append(task)
        return SolveResult(token="TOKEN", provider="fake", cost_usd=0.001)

    async def close(self):
        return None


def make_plague(engines, solver=None):
    return Plague(
        Config(solver="none", headless=True, humanize=False),
        engines=engines,
        solver=solver,
    )


def test_auto_escalates_from_lightpanda_to_cloak():
    fast = FakeEngine("lightpanda", [{"status": 403, "html": CF_HTML}])
    stealth = FakeEngine(
        "cloak", [{"status": 200, "html": CLEAN_HTML}], caps={Capability.VISUAL}
    )
    plague = make_plague({"lightpanda": fast, "cloak": stealth})

    result = asyncio.run(plague.fetch("https://blocked.test/"))

    assert result.ok
    assert result.engine == "cloak"
    assert result.status == 200
    assert len(result.attempts) == 2
    assert result.attempts[0].engine == "lightpanda"
    assert result.attempts[0].ok is False
    assert result.attempts[1].engine == "cloak"
    assert fast.opened == 1
    assert stealth.opened == 1


def test_fast_tier_stays_on_lightpanda():
    fast = FakeEngine("lightpanda", [{"status": 200, "html": CLEAN_HTML}])
    plague = make_plague({"lightpanda": fast})

    result = asyncio.run(plague.fetch("https://clean.test/", tier=Tier.FAST))

    assert result.engine == "lightpanda"
    assert len(result.attempts) == 1
    assert result.attempts[0].ok is True
    assert result.challenge is None


def test_screenshot_requirement_skips_lightpanda():
    fast = FakeEngine("lightpanda", [{"status": 200, "html": CLEAN_HTML}])
    stealth = FakeEngine(
        "cloak", [{"status": 200, "html": CLEAN_HTML}], caps={Capability.VISUAL}
    )
    plague = make_plague({"lightpanda": fast, "cloak": stealth})

    result = asyncio.run(
        plague.fetch("https://clean.test/", screenshot="out.png")
    )

    assert result.engine == "cloak"
    assert result.screenshot == "out.png"
    assert result.attempts[0].skipped
    assert "visual" in (result.attempts[0].skipped or "")
    assert fast.opened == 0


def test_solver_runs_on_stealth_tier(monkeypatch):
    fast = FakeEngine("lightpanda", [{"status": 403, "html": CF_HTML}])
    stealth = FakeEngine(
        "cloak",
        [
            {"status": 403, "html": RECAPTCHA_HTML},
            {"status": 200, "html": CLEAN_HTML},
        ],
        caps={Capability.VISUAL},
    )
    solver = FakeSolver()
    plague = make_plague({"lightpanda": fast, "cloak": stealth}, solver=solver)

    async def fake_inject(page, vendor, token):
        return True

    monkeypatch.setattr("plague.router.inject_token", fake_inject)

    result = asyncio.run(plague.fetch("https://blocked.test/"))

    assert result.ok
    assert result.engine == "cloak"
    assert result.solved is True
    assert len(solver.calls) == 1
    assert solver.calls[0].vendor == "recaptcha"
    assert solver.calls[0].sitekey == "SITE_KEY"
    final_attempt = result.attempts[-1]
    assert final_attempt.solver == "fake"
    assert final_attempt.cost_usd == pytest.approx(0.001)


def test_non_blocking_recaptcha_does_not_call_solver():
    stealth = FakeEngine(
        "cloak",
        [{"status": 200, "html": CLEAN_HTML.replace("</body>", RECAPTCHA_HTML)}],
        caps={Capability.VISUAL},
    )
    solver = FakeSolver()
    plague = make_plague({"cloak": stealth}, solver=solver)

    result = asyncio.run(plague.fetch("https://shop.test/", tier=Tier.STEALTH))

    assert result.ok
    assert result.solved is False
    assert solver.calls == []


def test_all_engines_failing_raises_with_attempts():
    fast = FakeEngine("lightpanda", [{"status": 403, "html": CF_HTML}])
    stealth = FakeEngine(
        "cloak", [{"status": 403, "html": CF_HTML}], caps={Capability.VISUAL}
    )
    plague = make_plague({"lightpanda": fast, "cloak": stealth})

    with pytest.raises(PlagueError) as caught:
        asyncio.run(plague.fetch("https://blocked.test/"))

    assert len(caught.value.attempts) == 2
    assert all(not attempt.ok for attempt in caught.value.attempts)


def test_fast_only_tier_does_not_escalate():
    fast = FakeEngine("lightpanda", [{"status": 403, "html": CF_HTML}])
    plague = make_plague({"lightpanda": fast})

    with pytest.raises(PlagueError):
        asyncio.run(plague.fetch("https://blocked.test/", tier=Tier.FAST))


def test_lightpanda_empty_app_shell_escalates():
    fast = FakeEngine("lightpanda", [{"status": 200, "html": APP_SHELL_HTML}])
    stealth = FakeEngine(
        "cloak", [{"status": 200, "html": CLEAN_HTML}], caps={Capability.VISUAL}
    )
    plague = make_plague({"lightpanda": fast, "cloak": stealth})

    result = asyncio.run(plague.fetch("https://app.test/"))

    assert result.engine == "cloak"
    assert result.attempts[0].ok is False
    assert "shell" in (result.attempts[0].error or "")


def test_probe_reports_challenge_without_escalation():
    fast = FakeEngine("lightpanda", [{"status": 403, "html": CF_HTML}])
    stealth = FakeEngine(
        "cloak", [{"status": 200, "html": CLEAN_HTML}], caps={Capability.VISUAL}
    )
    plague = make_plague({"lightpanda": fast, "cloak": stealth})

    probe = asyncio.run(plague.probe("https://blocked.test/"))

    assert probe.engine == "lightpanda"
    assert probe.challenge is not None
    assert probe.challenge.vendor == "cloudflare"
    assert stealth.opened == 0
