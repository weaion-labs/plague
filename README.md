# plague

CloakBrowser stealth. Lightpanda speed. One router.

[![tests](https://github.com/weaion-labs/plague/actions/workflows/tests.yml/badge.svg)](https://github.com/weaion-labs/plague/actions/workflows/tests.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![MCP](https://img.shields.io/badge/MCP-stdio-ff6a00.svg)](plague/mcp_server.py)

Plague is the missing router between a fast, rendering-free browser and a real
stealth Chromium. Clean pages go through a patched Lightpanda with Chrome's
network fingerprint. Walls escalate to CloakBrowser. Visual or reference work
goes to stock Chrome.

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

**Measured:** 71 ms warm p50, 155 MB per session, 100% on the local extraction
suite, and a matching Chrome TLS cipher and HTTP/2 fingerprint. See
[Speed and accuracy](#speed-and-accuracy).

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

## Speed and accuracy

Measured on local deterministic pages, `--repeat 3`. Full details in
[`benchmarks/README.md`](benchmarks/README.md).

| Engine | Cold fetch | Warm p50 | Accuracy | RSS |
|---|---:|---:|---:|---:|
| Lightpanda, patched | 1144 ms | 71 ms | 100% | 155 MB |
| Lightpanda, stock | 1123 ms | 69 ms | 100% | 149 MB |
| CloakBrowser | 778 ms | 84 ms | 100% | 848 MB |
| Chrome | 943 ms | 72 ms | 100% | 1052 MB |
| Playwright Chromium | 255 ms | 67 ms | 100% | 572 MB |

![Cold and warm latency](assets/benchmark-latency.png)

![Memory per session](assets/benchmark-memory.png)

The honest result:

- **One cold fetch:** raw Playwright wins. Lightpanda pays about one second of
  process startup. Plague's `fetch()` opens a fresh session each time.
- **Warm navigation:** all engines are close on small pages. Lightpanda is about
  twice as fast on a 180 KB content page because it has no layout tree.
- **Memory:** Lightpanda uses about 150 MB versus 850 MB for Cloak and 1050 MB
  for Chrome. Three Lightpanda sessions fit in 444 MB; three Chrome sessions
  needed about 2.9 GB.
- **Challenge detection:** 20 labeled local cases, 100% vendor, blocking, and
  solvable accuracy, with 100% blocking precision and recall.

For maximum speed on a list of pages, use a warm batch:

```bash
plague batch --tier fast --workers 4 urls.txt
```

Warm mode skips escalation by default. Add `--escalate` to fall back to the
next tier when a page is blocked.

The library exposes the same warm path:

```python
async with plague.session(tier="fast") as session:
    for url in urls:
        await session.goto(url)
        text = await session.text()
```

Or use the batch API directly:

```python
results = await plague.fetch_many(
    urls, tier="fast", workers=4, warm=True, escalate=False
)
```

## Install

The PyPI distribution name is `plague-browser`. Until the first release, install
from the clone:

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

# Reuse one session for a fast batch on clean pages
plague bench --warm --tier fast https://example.com https://news.ycombinator.com

# Production batch: one warm session per worker, optional escalation
plague batch --tier fast --workers 4 --escalate urls.txt

# Compare fingerprint surfaces across every engine
plague fingerprint --all
```

## Batch mode

`plague batch` is the production fast path. It opens one session per worker,
reuses it for every URL, and reports a challenge instead of escalating unless
you ask.

```bash
plague batch --tier fast --workers 4 urls.txt
plague batch --tier fast --workers 4 --escalate urls.txt
plague batch --tier stealth --workers 2 --screenshot-dir out/shots urls.txt
plague batch --tier fast --workers 4 --out out/results.json urls.txt
```

- `--workers 4` is reasonable for Lightpanda. Use 2 or fewer for Chrome or
  Cloak because each session costs about 850 MB to 1 GB.
- `--escalate` re-runs a blocked page through the next tier. It is slower but
  keeps the batch correct on protected pages.
- `--no-warm` opens a fresh session per URL, which is the old cold behavior.
- `--screenshot-dir` only writes files on visual tiers. Lightpanda has no
  screenshot.
- Results are also available as JSON with `--json` or `--out`.

`--tier` accepts `auto`, `fast`, `stealth`, and `chrome`.

## Patched Lightpanda (optional)

Stock Lightpanda is fast, but it announces itself: `Lightpanda/1.0`, Linux
platform, zero plugins, no `window.chrome`. The patch in
`patches/lightpanda-chrome-persona.patch` rebuilds it with a Chrome 146
Windows persona:

- Chrome User-Agent and Chrome client hints
- `Win32` platform, `Google Inc.` vendor, Chrome app version
- 8 hardware threads, Windows UA-CH platform
- 5 PDF plugins, 2 MIME types, `window.chrome`
- 1920x1080 screen values and consistent window dimensions
- Chrome TLS cipher set and HTTP/2 SETTINGS, window sizes, and pseudo-header order

It does not fake canvas, WebGL, or WebRTC. Those are still missing, and faking
them without a real rasterizer is easier to detect than an honest gap. The TLS
cipher hash and the Akamai HTTP/2 hash match Cloak. Four TLS extensions still
differ: `001b`, `0023`, `44cd`, and `fe0d`. Read
`docs/REVERSE_ENGINEERING.md` for the full comparison and
`patches/README.md` for build steps.

```bash
export PLAGUE_LIGHTPANDA_BIN=$PWD/.plague/lightpanda-src/zig-out/bin/lightpanda
plague fingerprint --tier fast --json
```

## MCP server (project-local)

The project ships a stdio MCP server in `plague/mcp_server.py`. It is configured
in `.opencode/opencode.json` and starts from the project root. Nothing is
installed globally and no global OpenCode configuration is changed.

```bash
opencode mcp list
# ✓ plague  connected
```

Tools exposed to the agent:

| Tool | What it does |
|---|---|
| `plague_doctor` | Engine availability, active solver, binary paths |
| `plague_fetch` | Fetch a URL through the tier router |
| `plague_detect` | Classify a challenge wall without solving |
| `plague_fingerprint` | Compare navigator, screen, client hints, canvas |
| `plague_bench` | Warm batch with workers and optional escalation |
| `plague_captcha_demos` | Run the public demo walls and classify results |

The server prefers the patched Lightpanda binary at
`.plague/lightpanda-src/zig-out/bin/lightpanda` when it exists. It also exposes
`plague://docs/reverse-engineering` and `plague://docs/readme` as resources.

`plague_bench` is warm and parallel by default. Pass `warm=false` for cold
fetches, `workers=N` for concurrency, and `escalate=true` to fall back to the
next tier on a blocked page.

Run it manually for debugging:

```bash
python3 -m plague.mcp_server
```

The server uses the Python environment that starts it. If you want strict
isolation, create a project venv and change the `command` in
`.opencode/opencode.json` to `.venv/bin/python`.

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
        print(len(result.cookies or []), "cookies")

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

# Also solve a widget on a page that loaded normally, for example a login form
plague fetch https://protected.example --tier stealth --solve-widgets
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

### Late-rendered widgets

Some sites build the widget after load, so the sitekey is not in the HTML. Plague
installs a render hook before page scripts run, records the sitekey, action, and
cdata from `turnstile.render`, `grecaptcha.render`, or `hcaptcha.render`, and
falls back to the widget DOM and its iframe. `--solve-widgets` also solves a
widget on a page that loaded normally, for example a login form.

For a non-blocking widget, `solved=true` means the token was injected. It does
not prove the site accepted it, because the form was not submitted. For a
blocking wall, the router reloads and re-checks, which is a real acceptance
signal.

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
| `PLAGUE_LIGHTPANDA_ARGS` | none | Extra `serve` arguments, shell-split |
| `PLAGUE_CHROME_EXECUTABLE` | auto | Chrome or Chromium path |
| `PLAGUE_CHROME_CHANNEL` | none | Playwright channel, for example `chrome` |
| `PLAGUE_CLOAK_LICENSE_KEY` | none | CloakBrowser Pro key |
| `PLAGUE_PROXY` | none | Default proxy URL |
| `PLAGUE_HEADLESS` | true | Headless mode |
| `PLAGUE_HUMANIZE` | true | Humanized input on Cloak |
| `PLAGUE_HUMAN_PRESET` | default | `default` or `careful` |
| `PLAGUE_GEOIP` | false | Match timezone and locale to the proxy IP (Cloak; needs `cloakbrowser[geoip]`) |
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
| `PLAGUE_MIN_TEXT_CHARS` | 40 | Empty app-shell escalation threshold |
| `PLAGUE_SOLVE_ON_FAST` | false | Allow token solving on Lightpanda (usually pointless) |
| `PLAGUE_SOLVE_PRESENT` | false | Solve token widgets even when the page is not blocked |
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
  fingerprint.py     cross-engine navigator and canvas probe
  mcp_server.py      project-local stdio MCP server
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
  cli.py             doctor, fetch, detect, batch, benchmark, fingerprint
scripts/
  captcha_matrix.py  run demo walls and record results
  make_assets.py     social preview and benchmark cards
benchmarks/
  server.py          local deterministic pages
  bench_speed.py     cold, warm, accuracy, memory, concurrency
  bench_detection.py detector precision and recall
patches/
  lightpanda-chrome-persona.patch
  curl-http2-chrome.patch
  README.md
docs/
  REVERSE_ENGINEERING.md
  BENCHMARK_STORY.md
  LAUNCH.md
  PUBLISHING.md
  MCP_PUBLISHING.md
  ORG_PROFILE_SNIPPET.md
  GOOD_FIRST_ISSUES.md
assets/
  social-preview.png
  benchmark-latency.png
  benchmark-memory.png
tests/
  test_detect.py     signature and false-positive tests
  test_router.py     escalation and solver flow with fake engines
  test_solver.py     provider payloads against mock HTTP
  test_text.py       HTML extraction
  test_integration.py real browser, local synthetic challenges
  test_mcp.py        stdio MCP handshake and tool catalog
```

## Development

```bash
python -m pytest                 # unit tests, no browsers
python -m pytest -m integration  # three browser tests plus MCP handshake
```

The integration tests serve local 403 pages with reCAPTCHA, hCaptcha, and
Turnstile-shaped widgets. The fake solver returns a token, injection fires the
page's `change` handler, the handler sets a clearance cookie, and the router
reloads into the clean page. They validate the full
detect -> solve -> inject -> reload path for all three token vendors against a
real browser. `test_mcp.py` starts the MCP server over stdio, lists its tools,
and calls `doctor`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and pull request rules. Report
security issues privately as described in [SECURITY.md](SECURITY.md).

## Verified in this repo

- Lightpanda nightly starts, exposes CDP, and serves pages over Playwright.
- CloakBrowser's stealth Chromium launches headless, reports
  `navigator.webdriver === false`, and takes screenshots.
- Stock Chrome works as the reference tier.
- Cloudflare and DataDome signatures classify correctly on live pages,
  including the important false-positive case where a widget or script is
  present but the page is not blocked.
- reCAPTCHA, hCaptcha, and Turnstile detection, token injection, cookie
  handoff, and reload pass against local synthetic challenges in a real
  browser.
- The patched Lightpanda build reports a Chrome UA, Win32 platform,
  `Google Inc.` vendor, 5 plugins, 2 MIME types, `window.chrome`, 8 hardware
  threads, and a 1920x1080 screen. Canvas, WebGL, and WebRTC are still absent.
- The patched build matches Cloak on the JA4 cipher hash
  (`8daaf6152771`) and the full Akamai HTTP/2 fingerprint
  (`52d84b11737d980aef856699f885ca86`). Four TLS extensions still differ.
- The CAPTCHA demo matrix in `scripts/captcha_matrix.py` records what each
  engine does. With no solver keys, token walls are detected but not solved.
  The NopeCHA Cloudflare demo still blocks both the patched Lightpanda and the
  free headless Cloak build.

What is not verified without keys: live CapSolver and 2Captcha calls, and live
solves on commercial anti-bot targets. The HTTP payloads are unit tested, but
vendor behavior changes.

The free headless Cloak build still fails the NopeCHA Cloudflare demo. That is
a real boundary: a newer paid build, a headed window, and a residential IP are
the levers for that class of target.

## Roadmap

- Close the four missing TLS extensions: `001b`, `0023`, `44cd`, `fe0d`.
- Canvas and WebGL rasterization, if Lightpanda grows a layout engine.
- Persistent profile pools with GeoIP and proxy rotation.
- More solver providers and per-domain routing policies.
- Success and cost telemetry per target.

If Plague saves you time, a star helps other people find it.

## Legal and ethical note

CAPTCHA bypass and anti-bot circumvention can violate a site's terms of service
and, depending on jurisdiction and intent, laws against unauthorized access.
Solver providers have their own rules about permitted targets. Decide where
your line is before you point this at someone else's site. Plague is a routing
and instrumentation tool, not a license to ignore those constraints.
