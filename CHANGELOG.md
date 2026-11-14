# Changelog

## Unreleased

- Added a Patchright engine and `tier="patchright"`: patched Playwright
  Chromium with runtime stealth, no license server, no seat limit. Auto
  escalation now runs Lightpanda, then Patchright, then Cloak, then Chrome.
- Added named per-program profiles to `launch` with `profile="name"`, stored
  under `.plague/profiles/`.
- Fixed auto escalation never running when the fast tier was not pinned.

- Added `read` for a fast Lightpanda-only text and link read, with a hint to
  escalate when the page needs rendering.
- Added `launch` to open Cloak, Chrome, or Lightpanda as a first-class MCP
  session, with per-session `profile_dir`, `headed`, `proxy`, and `storage`.
- Added `captcha` for on-demand challenge status and solving on the current
  page. It reports blocking state, sitekey, solver status, cost, and outcome.
- Sessions now keep the last navigation status and headers, so challenge
  detection on an already-open page is accurate instead of guessing from the
  DOM alone.

- Added warm MCP sessions: one long-lived fast-tier browser is reused across
  `fetch` calls, with an idle timeout and automatic cold retry when a session
  dies.
- Added ref-based interaction: `snapshot` returns compact `eN` refs and `act`
  runs click, fill, press, hover, select, check, uncheck, wait, evaluate,
  scroll, back, and goto against a ref or a CSS selector.
- Added `fetch` actions so a read can fill a form or click a control before
  extraction.
- Added headed handoff: `handoff` launches a dedicated-profile Chrome, or
  attaches to an existing CDP endpoint with `attach_to`, seeds cookies from the
  live session, and returns an attach hint. Linux launches pick Wayland when
  available, with `PLAGUE_HANDOFF_OZONE` to force it. `act tier="handoff"`
  drives it directly, or Playwright MCP can attach over CDP. `release` closes a
  launched browser and detaches from an attached one.
- Added `PLAGUE_ALLOWED_DOMAINS` navigation allowlist and
  `PLAGUE_SOLVE_DOMAINS` solver allowlist.
- Added `PLAGUE_POLICY=open|warn|block|strict`, default `open`, so allowlists
  are advisory unless enforcement is requested. Added
  `PLAGUE_SOLVE_MODE=auto|always|never`.
- Added saved action recipes: `recipe_save`, `recipe_run`, `recipe_list`, and
  `recipe_delete`, stored as JSON under `.plague/recipes/`.
- Added bounded recon observation: `network` and `console` report requests,
  responses, console messages, and uncaught page errors from the warm session.
  `network include_body=true` returns text, JSON, XML, or JavaScript bodies.
- Added `screenshot` for rendering tiers and `tabs`, `tab_open`, `tab_switch`,
  and `tab_close` for Chrome and Cloak.
- Added `storage_save`, `storage_load`, `storage_list`, and `storage_delete` for
  reusing cookies and localStorage across runs. State files are owner-only.
- Added per-host tier pinning: an explicit stealth or chrome fetch keeps `auto`
  on that tier for `PLAGUE_HOST_TIER_TTL` seconds, so an authenticated flow does
  not fall back to Lightpanda.
- Interactive tools now default to the most recently used tier, so follow-up
  `act`, `snapshot`, `network`, and `screenshot` calls stay on the same session.
- Added `set_files` as an action type for file uploads.
- Added `network_export` for HAR and curl export, and header capture in
  `network include_headers=true`.
- Popups and new tabs opened by the page are observed automatically through the
  browser context.
- Added `api_request` for authenticated API testing with the warm session
  cookies, including cookies from an attached or launched handoff browser. It
  uses `curl_cffi` Chrome impersonation by default, with plain `httpx` as the
  fallback.
- Added warm-session, handoff, and policy telemetry to `doctor`.
- Refactored challenge handling into one resolver used by both cold and warm
  fetches, so warm pages get JS interstitial waits and token solving too.
- Added tests for action parsing, refs, snapshots, policy gates, warm sessions,
  and the handoff helpers.

## 0.1.0 - 2026-11-06

- Added the tiered router: Lightpanda fast tier, CloakBrowser stealth tier,
  stock Chrome reference tier, with capability filtering and escalation.
- Added challenge detection for Cloudflare, Turnstile, reCAPTCHA v2 and v3,
  hCaptcha, DataDome, PerimeterX, Kasada, Akamai, Imperva, AWS WAF, Vercel, and
  generic HTTP blocks.
- Added CapSolver, 2Captcha, and manual token solving, plus token injection and
  reload.
- Added live sitekey capture from render hooks, widget DOM, and iframes.
- Added `--solve-widgets` for token widgets on pages that are not blocked.
- Built a patched Lightpanda with a Chrome 146 persona, Chrome client hints,
  Chrome TLS cipher set, and Chrome HTTP/2 fingerprint.
- Matched CloakBrowser on the JA4 cipher hash and the full Akamai HTTP/2 hash.
- Added warm sessions, `fetch_many`, `plague batch`, worker concurrency, and
  optional escalation.
- Added the project-local stdio MCP server with fetch, detect, fingerprint,
  bench, doctor, and CAPTCHA demo tools.
- Added cold, warm, accuracy, memory, concurrency, and detector benchmarks.
- Added 42 unit tests and 4 integration tests, including a real-browser token
  injection test for reCAPTCHA, hCaptcha, and Turnstile.
