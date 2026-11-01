"""End-to-end tests of detect -> solve -> inject -> reload on a local server.

Marked as integration because they launch a real Chromium. Run with:

    pytest -m integration tests/test_integration.py
"""

from __future__ import annotations

import asyncio
import http.server
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from plague.challenge.solvers.base import SolveResult
from plague.config import Config, find_chrome
from plague.engines.chrome import ChromeEngine
from plague.models import Tier
from plague.router import Plague

CLEAN_HTML = """
<html><head><title>Real page</title></head>
<body><h1>Welcome</h1><p>This is the real content.</p></body></html>
"""

CASES = {
    "recaptcha": {
        "field": "g-recaptcha-response",
        "markup": '<div class="g-recaptcha" data-sitekey="LOCAL_SITEKEY"></div>',
    },
    "hcaptcha": {
        "field": "h-captcha-response",
        "markup": '<div class="h-captcha" data-sitekey="LOCAL_SITEKEY"></div>',
    },
    "cloudflare_turnstile": {
        "field": "cf-turnstile-response",
        "markup": '<div class="cf-turnstile" data-sitekey="LOCAL_SITEKEY"></div>',
    },
}


def challenge_html(vendor: str) -> str:
    case = CASES[vendor]
    return f"""
<html><head><title>Verify you are human</title></head>
<body>
  {case["markup"]}
  <textarea name="{case["field"]}"></textarea>
  <script>
    document.querySelector('textarea[name={case["field"]}]')
      .addEventListener('change', () => {{
        document.cookie = 'clearance=1; path=/';
      }});
  </script>
</body></html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        query = parse_qs(urlparse(self.path).query)
        vendor = (query.get("vendor") or ["recaptcha"])[0]
        cookie = self.headers.get("Cookie") or ""
        if "clearance=1" in cookie:
            body, status = CLEAN_HTML, 200
        else:
            body, status = challenge_html(vendor), 403
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        return None


class LocalSolver:
    name = "local"

    def __init__(self) -> None:
        self.calls = []

    async def solve(self, task):
        self.calls.append(task)
        return SolveResult(token="LOCALTOKEN", provider="local", cost_usd=0.0)

    async def close(self) -> None:
        return None


@pytest.mark.integration
@pytest.mark.parametrize("vendor", list(CASES))
def test_solver_clears_a_local_challenge(vendor: str):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/?vendor={vendor}"

    config = Config(
        solver="none",
        headless=True,
        humanize=False,
        timeout_ms=20_000,
        chrome_executable=find_chrome(),
    )
    config.js_challenge_rounds = 1
    config.js_challenge_wait_ms = 100
    solver = LocalSolver()
    plague = Plague(
        config, engines={"chrome": ChromeEngine(config)}, solver=solver
    )

    async def run():
        try:
            return await plague.fetch(
                url, tier=Tier.CHROME, wait_until="domcontentloaded"
            )
        finally:
            await plague.close()

    try:
        result = asyncio.run(run())
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"chromium unavailable: {exc}")
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok
    assert result.engine == "chrome"
    assert result.solved is True
    assert "Welcome" in result.text
    assert len(solver.calls) == 1
    assert solver.calls[0].vendor == vendor
    assert solver.calls[0].sitekey == "LOCAL_SITEKEY"
