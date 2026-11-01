# plague

Tiered browser orchestration for people who want Lightpanda speed without
giving up Chrome compatibility or stealth.

Plague is not a new browser engine. It is a router with three interchangeable
backends, plus a challenge detector and a token-solver layer:

```
plague.fetch(url)
  |
  +-- policy and capability filter
        |
        +-- lightpanda   fast, no layout engine, cheap
        +-- cloak        patched stealth Chromium
        +-- chrome       stock Chromium or Google Chrome
  |
  +-- challenge detector
        |
        +-- token wall   -> solver -> inject -> reload
        +-- JS wall      -> wait, click Turnstile, reload
        +-- risk wall    -> escalate to the stealth tier
```

The important design decision: these engines are alternatives, not layers.
Chrome and CloakBrowser are both Chromium. Lightpanda is a different species.
Plague picks one per attempt and escalates when a wall appears. It never
pretends a rendering-free browser is Chrome.

## What it actually does

- Runs a Lightpanda pass first. On ordinary content pages this is much cheaper
  and faster than Chromium.
- Detects when that pass hit a wall and retries the job on CloakBrowser with a
  real fingerprint, real layout, and humanized input.
- Recognizes token-based challenges, asks a solver for a token, injects it into
  the correct hidden fields, calls the known callbacks, and reloads.
- Recognizes the walls that cannot be solved with a token and says so instead
  of burning money on solver credits.
- Reports which engine won, what it cost, and what it saw.

## What it does not do

- It does not make Lightpanda render like Chrome. That would mean rebuilding
  Blink, layout, paint, and the compositor. Lightpanda's speed exists because
  those are absent.
- It does not bypass every CAPTCHA. Nobody does. Token-based challenges can be
  solved. Risk-score systems cannot be bought out; they score your TLS,
  fingerprint, IP reputation, and behavior.
- It does not make a datacenter IP look residential. For hard targets, bring a
  residential proxy.

If a tool promises "passes all bot detection forever," it is a demo, not a
system.

## Engine capability matrix

| | Lightpanda | CloakBrowser | Chrome |
|---|---|---|---|
| Engine | Zig + V8, no layout | Patched Chromium | Chromium |
| Relative speed | ~9x faster | Chrome | Chrome |
| Relative memory | ~16x less | Chrome | Chrome |
| Real layout / screenshots | No (placeholder PNG) | Yes | Yes |
| PDF, video, tracing | No | Yes | Yes |
| Extensions, downloads | No | Yes | Yes |
| Network interception | Yes | Yes | Yes |
| Cookie and storage state | Yes | Yes | Yes |
| Looks like Chrome | No | Yes | Stock automation tells |
| Token CAPTCHA solving | No (escalates) | Yes | Yes |
| Best use | Bulk discovery, extraction | Protected targets | Dev, CI, visual checks |

Lightpanda's speed and memory numbers are vendor benchmarks (933 pages on an
AWS m5.large). They describe the happy path. The metric that matters is
successful pages per dollar, including escalations.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium

# Lightpanda nightly for this platform
plague doctor --install

# Check what is available
plague doctor
```

CloakBrowser downloads its Chromium binary on first launch (about 200 MB). The
free build is older than the paid one and is limited to one concurrent session.
Set `PLAGUE_CLOAK_LICENSE_KEY` or `CLOAKBROWSER_LICENSE_KEY` for the current
build.

## Quickstart

```bash
# Automatic tier selection: Lightpanda first, escalate on a wall
plague fetch https://example.com

# Fast only, no escalation
plague fetch https://example.com --tier fast

# Stealth only, with a proxy and humanized input
plague fetch https://protected.example --tier stealth \
  --proxy http://user:pass@residential-proxy:8080 --headed

# Visual output forces a rendering engine
plague fetch https://example.com --screenshot out/page.png

# Classify the wall without solving or escalating
plague detect https://protected.example --tier stealth

# Compare engines and latency across a list
plague bench https://example.com https://news.ycombinator.com --tier auto
```

`--tier` accepts `auto`, `fast`, `stealth`, and `chrome`.

## Library

```python
import asyncio

from plague import Plague, Tier


async def main():
    async with Plague() as plague:
        result = await plague.fetch("https://example.com", tier=Tier.AUTO)
        print(result.engine, result.status, result.elapsed_ms, "ms")
        print(result.title)
        print(result.text[:500])

        for attempt in result.attempts:
            print(attempt.engine, attempt.ok, attempt.challenge, attempt.elapsed_ms)


asyncio.run(main())
```

Interactions before extraction:

```python
from plague import Action

result = await plague.fetch(
    "https://example.com",
    actions=[
        Action(type="click", selector="#load-more"),
        Action(type="wait", value="1000"),
        Action(type="fill", selector="input[name=q]", value="plague"),
        Action(type="press", selector="input[name=q]", value="Enter"),
    ],
)
```

## Challenge handling

Plague separates four kinds of walls:

| Kind | Examples | What Plague does |
|---|---|---|
| Token | reCAPTCHA v2, hCaptcha, Turnstile | Solver -> inject -> reload |
| JS interstitial | Cloudflare IUAM, Vercel challenge | Wait, click Turnstile, reload |
| Risk score | reCAPTCHA v3, DataDome, Kasada, Akamai, PerimeterX, Imperva | Escalate to Cloak, no credits spent |
| HTTP block | 401, 403, 429, 503 with no signature | Escalate, report status |

The detector is deliberately conservative. A reCAPTCHA widget on a contact
form is not a block; escalating there would be wrong and expensive. A page is
only treated as blocked when a mitigation header says so, the status is
hostile, an interstitial phrase is present, or the URL looks like a challenge
endpoint.

### Solvers

```bash
export CAPSOLVER_API_KEY=...
# or
export TWOCAPTCHA_API_KEY=...

plague fetch https://protected.example --tier stealth
```

Supported:
- reCAPTCHA v2 (including Enterprise) via CapSolver and 2Captcha
- hCaptcha
- Cloudflare Turnstile
- Manual solving in a headed window: `--manual --headed`

Not supported by design:
- reCAPTCHA v3 has no token to buy. It is a score.
- DataDome, Kasada, Akamai, PerimeterX, and Imperva are risk engines. There is
  no token endpoint. The answer is a better browser identity, a residential
  IP, and warmed profiles, in that order.
- AWS WAF is detected but not solved in v1; its challenge needs more parameters
  than a sitekey.

Solver prices in the telemetry are estimates, not a bill.

### Manual solving

```bash
plague fetch https://protected.example --tier stealth --manual --headed
```

The router opens a real window, waits for the widget, and polls the standard
response fields until you finish. On a headless server, run it under Xvfb.

## Configuration

All settings can come from the environment.

| Variable | Default | Meaning |
|---|---|---|
| `PLAGUE_LIGHTPANDA_BIN` | auto | Path to the Lightpanda binary |
| `PLAGUE_LIGHTPANDA_PORT` | random | Fixed CDP port, or 0 for a free port |
| `PLAGUE_CHROME_EXECUTABLE` | auto | Chrome or Chromium path |
| `PLAGUE_CHROME_CHANNEL` | none | Playwright channel, for example `chrome` |
| `PLAGUE_CLOAK_LICENSE_KEY` | none | CloakBrowser Pro key |
| `PLAGUE_PROXY` | none | Default proxy URL |
| `PLAGUE_HEADLESS` | true | Headless mode |
| `PLAGUE_HUMANIZE` | true | Humanized input on Cloak |
| `PLAGUE_LOCALE` | en-US | Locale |
| `PLAGUE_TIMEZONE` | none | Timezone |
| `PLAGUE_TIMEOUT_MS` | 30000 | Navigation timeout |
| `PLAGUE_PROFILE_DIR` | none | Persistent profile directory |
| `PLAGUE_SOLVER` | auto | `auto`, `none`, `capsolver`, `2captcha`, `manual` |
| `CAPSOLVER_API_KEY` | none | CapSolver key |
| `TWOCAPTCHA_API_KEY` | none | 2Captcha key |
| `PLAGUE_SOLVER_TIMEOUT_S` | 180 | Solver polling timeout |
| `PLAGUE_MANUAL_TIMEOUT_S` | 300 | Manual solve timeout |
| `PLAGUE_JS_ROUNDS` | 3 | Reloads for JS interstitials |
| `PLAGUE_JS_WAIT_MS` | 2500 | Wait per JS round |
| `PLAGUE_SOLVE_ON_FAST` | false | Allow token solving on Lightpanda (usually pointless) |
| `PLAGUE_HOME` | ./.plague or ~/.cache/plague | Cache and log directory |

## How escalation works

1. Try the first tier in the chain.
2. Navigate and detect.
3. If it is a token wall and a solver is configured, solve, inject, reload.
4. If it is a JS wall on a rendering engine, wait, click Turnstile if present,
   reload, and re-check.
5. If it is still blocked, close the session and start the next tier from
   scratch.
6. Never carry a live session across engines. Cookies and storage state can be
   exported, but TLS, Client Hints, cache, and fingerprint cannot.

The tier chains:

| Tier | Chain |
|---|---|
| `auto` | lightpanda -> cloak -> chrome |
| `fast` | lightpanda |
| `stealth` | cloak |
| `chrome` | chrome |

A screenshot request filters out engines without visual rendering, so `auto`
will skip Lightpanda and go straight to Cloak.

## Project layout

```
plague/
  router.py          tier selection, escalation, telemetry
  engines/
    lightpanda.py    process + CDP client
    cloak.py         CloakBrowser wrapper
    chrome.py        Playwright Chromium/Chrome
    base.py          Session, Nav, capabilities, proxy handling
  challenge/
    detect.py        signatures and blocking heuristics
    inject.py        token fields, events, reCAPTCHA callbacks
    actions.py       Turnstile checkbox clicks
    solvers/         CapSolver, 2Captcha, manual
  cli.py             doctor, fetch, detect, bench
tests/
  test_detect.py     signature and false-positive tests
  test_router.py     escalation and solver flow with fake engines
  test_solver.py     provider payloads against mock HTTP
  test_text.py       HTML extraction
  test_integration.py real browser, local synthetic challenge
```

## Development

```bash
python -m pytest                 # unit tests, no browsers
python -m pytest -m integration  # one real Chromium test
```

The integration test serves a local 403 page with a reCAPTCHA-shaped widget.
The solver returns a fixed token, injection fires the page's `change` handler,
the handler sets a clearance cookie, and the router reloads into the clean page.
It validates the full detect -> solve -> inject -> reload path against a real
browser.

## Verified in this repo

- Lightpanda nightly starts, exposes CDP, and serves pages over Playwright.
- CloakBrowser's stealth Chromium launches headless, reports
  `navigator.webdriver === false`, and takes screenshots.
- Stock Chrome works as the reference tier.
- Cloudflare, DataDome, and reCAPTCHA signatures classify correctly on live
  pages, including the important false-positive case where a widget is present
  but the page is not blocked.
- The synthetic challenge flow passes end to end.

What is not verified without keys: live CapSolver and 2Captcha calls, and live
solves on commercial anti-bot targets. The HTTP payloads are unit tested, but
vendor behavior changes.

## Legal and ethical note

CAPTCHA bypass and anti-bot circumvention can violate a site's terms of service
and, depending on jurisdiction and intent, laws against unauthorized access.
Solver providers have their own rules about permitted targets. Decide where
your line is before you point this at someone else's site. Plague is a routing
and instrumentation tool, not a license to ignore those constraints.
