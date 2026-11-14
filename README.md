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
- Keeps one warm fast session across MCP tool calls, so a browsing loop pays a
  navigation instead of a process start.
- Lets an agent act on the page with snapshot refs instead of generating
  Playwright scripts: click, fill, press, select, scroll, back.
- Records requests, responses, console messages, and page errors for recon,
  and replays authenticated API calls with the session cookies.
- Saves and reloads storage states so a login survives a restart.
- Hands off to a headed Chrome with a dedicated profile and a CDP endpoint when
  a login, 2FA prompt, payment, or risk-score wall needs a human.
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

| | Lightpanda | Patchright | CloakBrowser | Chrome |
|---|---|---|---|---|
| Engine | Zig + V8, no layout | Patched Playwright Chromium | Patched Chromium | Chromium |
| Relative speed | ~9x faster | Chrome | Chrome | Chrome |
| Relative memory | ~16x less | Chrome | Chrome | Chrome |
| Real layout / screenshots | No (placeholder PNG) | Yes | Yes | Yes |
| PDF, video, tracing | No | Yes | Yes | Yes |
| Extensions, downloads | No | Yes | Yes | Yes |
| Network interception | Yes | Yes | Yes | Yes |
| Cookie and storage state | Yes | Yes | Yes | Yes |
| Looks like Chrome | No | Runtime stealth, no license | Yes | Stock automation tells |
| Token CAPTCHA solving | No (escalates) | Yes | Yes | Yes |
| Best use | Bulk discovery, extraction | No-login interactive work | Protected targets | Dev, CI, visual checks |

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
pip install -e ".[impersonate]"   # optional: browser-impersonated API replay
pip install -e ".[stealth]"       # optional: Patchright no-license stealth tier
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

# No-license stealth-lite Chromium
plague fetch https://protected.example --tier patchright --headed

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
| `plague_doctor` | Engine availability, active solver, policy, warm sessions, handoff state |
| `plague_fetch` | Fetch a URL through the tier router, with optional actions |
| `plague_read` | Fast Lightpanda-only text and links, no rendering |
| `plague_launch` | Open Cloak, Patchright, Chrome, or Lightpanda and make it the active session |
| `plague_captcha` | Inspect the current challenge, or solve it on demand |
| `plague_snapshot` | Interactive elements as compact refs such as `e3` |
| `plague_act` | Click, fill, press, select, scroll, back, goto on refs or selectors |
| `plague_network` | Request log with method, URL, resource type, and status |
| `plague_network_export` | Export the request log as HAR or curl commands |
| `plague_console` | Console messages and uncaught page errors |
| `plague_api_request` | Raw HTTP request with the warm session cookies |
| `plague_screenshot` | Capture the current rendering page |
| `plague_tabs` | List active pages |
| `plague_tab_open` | Open a page and make it active |
| `plague_tab_switch` | Switch the active page |
| `plague_tab_close` | Close a page |
| `plague_storage_save` | Save cookies and localStorage under a name |
| `plague_storage_load` | Reopen a tier with a saved storage state |
| `plague_storage_list` | List saved storage states |
| `plague_storage_delete` | Delete a saved storage state |
| `plague_handoff` | Launch a headed Chrome and return its CDP URL |
| `plague_release` | Close the handoff browser and optionally the warm sessions |
| `plague_recipe_save` | Save an action list as a reusable recipe |
| `plague_recipe_run` | Replay a saved recipe, optionally after navigating |
| `plague_recipe_list` | List saved recipes |
| `plague_recipe_delete` | Delete a saved recipe |
| `plague_detect` | Classify a challenge wall without solving |
| `plague_fingerprint` | Compare navigator, screen, client hints, canvas |
| `plague_bench` | Warm batch with workers and optional escalation |
| `plague_captcha_demos` | Run the public demo walls and classify results |

### Warm sessions

The MCP server keeps one fast-tier session alive between tool calls and closes
it after `PLAGUE_MCP_IDLE_S` seconds (default 180). The first `fetch` pays
Lightpanda startup; later calls reuse the same process and the same cookies.

```text
fetch  https://example.com            # 640 ms cold
fetch  https://example.com            # 110 ms warm
snapshot                              # refs: e1 link "Learn more"
act    [{"type": "click", "ref": "e1"}]
```

The loop is deliberately tool-shaped, not script-shaped. A tool call cannot have
a syntax error, and a ref cannot silently point at a different element after a
CSS class changes. Refs are only valid until the page navigates or the DOM
changes, so take a fresh `snapshot` after a step that mutates the page.

`tier=patchright`, `tier=stealth`, and `tier=chrome` also keep a warm session,
one heavy session at a time. `tier=auto` uses the fast session and falls back to
Patchright, then Cloak, on a wall, which keeps memory and Cloak concurrency seats
low. For an interactive flow on a protected page, call `fetch` with
`tier="patchright"` for the no-license stealth-lite tier, or `tier="stealth"`
for Cloak, so the session stays warm for `act`. Set
`PLAGUE_MCP_KEEP_STEALTH=1` if you want auto escalation to keep the heavy
session warm too.

After a successful `tier="patchright"`, `tier="stealth"`, or `tier="chrome"`
fetch, that host stays pinned to the heavy tier for `PLAGUE_HOST_TIER_TTL`
seconds (default 600).
`tier="auto"` then reuses the same session, so an authenticated flow keeps its
cookies instead of dropping back to Lightpanda. `release(all_sessions=True)`
clears the pins.

Interactive tools (`act`, `snapshot`, `network`, `console`, `screenshot`,
`tabs`, `storage_save`) default to `tier="auto"`, which means the most recently
used tier. After a stealth fetch you do not have to repeat the tier on every
follow-up call.

### Fast reads, launch, and captcha

`read` is deliberately the fast path. It uses Lightpanda only and returns text
plus links. It does not render or escalate, so it fails with a hint when the
page is a JS app or a wall.

```text
read https://docs.example/page
```

`launch` is the explicit way to open a rendering tier and keep it active. Use
`tier="stealth"` for Cloak, `tier="chrome"` for stock Chrome, or `tier="fast"`
for Lightpanda. It accepts `profile_dir`, `headed`, `proxy`, and `storage`, so a
bounty can get its own identity.

```text
launch tier=stealth url=https://target.example/login
launch tier=chrome profile_dir=./.playwright-profile
```

`captcha` inspects or solves the page that is already open.

```text
captcha action=status
captcha action=solve
```

It reports the vendor, kind, blocking state, sitekey, and whether a solver is
configured. Solving needs `CAPSOLVER_API_KEY` or `TWOCAPTCHA_API_KEY`. In
`PLAGUE_SOLVE_MODE=always`, it also attempts risk-classified pages that expose a
sitekey, but a page with no token cannot be solved by any provider.

### Recon: requests and logs

The warm session records requests, responses, console messages, and uncaught
errors. This is the part that matters on a bug bounty target: you see the XHR
and API paths the page actually uses, not just the rendered text.

```text
network filter=api limit=50 include_body=true
# [{method: GET, url: https://target/api/users, status: 200,
#   body: "{\"users\":[...]}"}]
console filter=error
# [{source: page, type: error, text: "Uncaught TypeError: ..."}]
```

`network` and `console` do not open a browser. If no warm session exists they
return an empty list with a note.

`api_request` replays a request with the cookies from the active warm session.
If no warm session has cookies, it uses the handoff browser, which is what you
want right after a human login. It is the fast path for testing an endpoint you
just observed. By default it uses `curl_cffi` with Chrome impersonation, so it
carries a real Chrome TLS and HTTP/2 fingerprint instead of a Python one. Set
`impersonate="none"` to force plain `httpx`, or install the extra with
`pip install -e ".[impersonate]"` if it is missing.

`network_export` writes the observed log as HAR, which DevTools and report
tooling understand, or as ready-to-run curl commands. Both contain live cookies
and headers, so treat the files as secrets.

```text
network filter=api include_body=true
api_request GET https://target/api/users
network_export format=har filter=api
network_export format=curl filter=api
```

### Screenshots

`screenshot` needs a rendering engine. The fast tier has no layout, so use
`tier="stealth"`, `tier="chrome"`, or `tier="handoff"`. With no path it writes
under `.plague/screenshots/`.

### Tabs

`tabs`, `tab_open`, `tab_switch`, and `tab_close` work on Chrome and Cloak.
Lightpanda exposes one page and returns a clear error on `tab_open`, so use the
fast tier for reading and a rendering tier for OAuth or popup flows.

### Session storage

`storage_save` exports cookies and localStorage from the current session.
`storage_load` reopens a tier with that state, so a login done once survives a
server restart. `storage_save tier="handoff"` exports the human-driven browser,
which is how you keep a login that needed a manual step.

```text
storage_save name=program-x
release
storage_load name=program-x tier=stealth url=https://target/login
```

States are written owner-only under `.plague/sessions/`. They contain live
cookies, so treat them like credentials.

### Recipes

An action list that works can be stored and replayed:

```text
recipe_save name=login actions=[{"type":"fill","ref":"e1","value":"me"},
                                 {"type":"click","ref":"e2"}]
recipe_run  name=login url=https://target.example/login
```

Recipes are JSON under `.plague/recipes/` (or `PLAGUE_HOME/recipes`). Replaying
one is deterministic and cannot have a syntax error, which is the point.

### Headed handoff

```text
handoff url=https://target.example/login
# -> CDP URL on 127.0.0.1, dedicated profile, cookies seeded if available
```

On Linux the launch picks Wayland when the session provides it and falls back to
X11. Force one with `PLAGUE_HANDOFF_OZONE=wayland` or `x11`. On macOS and
Windows the display check is skipped.

To drive a browser you started yourself, or one on another machine, use attach
mode. It skips the display check entirely:

```text
handoff attach_to=http://127.0.0.1:9222 url=https://target.example/login
```

Chrome 136 and later require a non-default profile for remote debugging:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/plague-handoff
```

For a headless VPS, run Chrome on your workstation and forward the port over
SSH (`ssh -L 9222:127.0.0.1:9222 vps`), then attach. For a cloud browser, pass
its CDP URL to `attach_to`.

The human completes the login or challenge in the headed window. The agent can
then keep driving it with `act tier="handoff"`, or attach another harness to the
returned endpoint:

```bash
npx @playwright/mcp@latest --cdp-endpoint=http://127.0.0.1:9222
```

`release` closes a browser Plague launched, and only detaches from one it
attached to. The profile is separate from the daily Chrome profile and from the
platform profile. Keep target work and platform work in different directories.

The handoff observer sees traffic only while a Plague tool is attached, so for a
continuous capture of a human-driven session use the Chrome DevTools protocol
from another client.

### Policy

Open by default. With `PLAGUE_POLICY=open`, the domain lists are advisory and
nothing blocks a navigation.

- `PLAGUE_POLICY=open` (default), `warn`, `block`, or `strict`.
- `warn` logs an out-of-list navigation but proceeds.
- `block` refuses an out-of-list navigation.
- `strict` also enforces `PLAGUE_SOLVE_DOMAINS` and keeps the audit trail.
- `PLAGUE_ALLOWED_DOMAINS` is the navigation list.
- `PLAGUE_SOLVE_DOMAINS` is the solver list.
- `PLAGUE_SOLVE_MODE=auto` matches token walls. `always` also attempts any
  challenge where a sitekey exists. `never` disables the solver.

`always` cannot make a risk-score wall solvable. DataDome, Kasada, PerimeterX,
and reCAPTCHA v3 have no token to buy, so an attempt there will usually fail and
may spend credits. It is a "try it" switch, not a bypass.

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
| `PLAGUE_POLICY` | open | `open`, `warn`, `block`, or `strict` allowlist enforcement |
| `PLAGUE_SOLVE_MODE` | auto | `auto`, `always`, or `never` solver behavior |
| `PLAGUE_ALLOWED_DOMAINS` | none | Comma or space separated navigation allowlist |
| `PLAGUE_SOLVE_DOMAINS` | none | Domains where the token solver may run |
| `PLAGUE_MCP_IDLE_S` | 180 | Idle seconds before the MCP server closes a warm session |
| `PLAGUE_MCP_KEEP_STEALTH` | false | Keep the auto-escalated Patchright or Cloak session warm for follow-up `act` calls |
| `PLAGUE_HOST_TIER_TTL` | 600 | Seconds a host stays pinned to stealth or chrome after an explicit fetch |
| `PLAGUE_SCREENSHOT_DIR` | .plague/screenshots | Default output directory for `screenshot` |
| `PLAGUE_HANDOFF_PORT` | 0 | Fixed CDP port for the headed handoff, or 0 for a free port |
| `PLAGUE_HANDOFF_OZONE` | auto | `auto`, `wayland`, or `x11` for the headed handoff |
| `PLAGUE_HANDOFF_PROFILE_DIR` | .plague/handoff-profile | Profile directory for the headed handoff |
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
| `auto` | lightpanda -> patchright -> cloak -> chrome |
| `fast` | lightpanda |
| `patchright` | patchright |
| `stealth` | cloak |
| `chrome` | chrome |

A screenshot request filters out engines without visual rendering, so `auto`
will skip Lightpanda and start with Patchright.

## Project layout

```
plague/
  router.py          tier selection, escalation, telemetry
  fingerprint.py     cross-engine navigator and canvas probe
  interact.py        action parsing and execution
  snapshot.py        ref-based interactive element snapshots
  observe.py         bounded request, console, and error log
  harexport.py       HAR and curl export from the request log
  storage.py         named storage states for session reuse
  http.py            raw HTTP with browser impersonation
  recipes.py         saved action lists for deterministic replay
  handoff.py         headed Chrome over CDP, dedicated profile
  mcp_server.py      project-local stdio MCP server
  engines/
    lightpanda.py    process + CDP client
    patchright.py    patched Playwright, no-license stealth
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
- The MCP server reuses one warm Lightpanda session across calls and returns
  ref snapshots that `act` can drive, verified against a local page.
- The headed handoff launches Chrome with a dedicated profile, exposes CDP,
  and can be driven through `act tier="handoff"`.
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
