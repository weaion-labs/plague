# Agent browser landscape: Browse, Playwright MCP, and Plague

Status: analysis notes, written 2026-11-11. Nothing here was benchmarked
locally. Items marked **UNVERIFIED** need a source read or a live test before
anyone builds on them.

Source for the first section: <https://opencode.ai/product/browse> and its
repository pointer `github.com/anomalyco/browse`. Source for the third section
is this repository.

---

## 0. Correction to an earlier read

An earlier pass over the bugger-kit said captcha solving was absent from this
stack. That was wrong. Plague already ships the token-solver layer:

- `plague/challenge/solvers/` with `capsolver.py` and `twocaptcha.py`, plus a
  manual provider selected through `PLAGUE_SOLVER=manual`.
- `plague/config.py:113` `solver: auto | none | capsolver | 2captcha | manual`,
  keys from `CAPSOLVER_API_KEY` and `TWOCAPTCHA_API_KEY`.
- Detection for Cloudflare, Turnstile, reCAPTCHA v2 and v3, hCaptcha,
  DataDome, PerimeterX, Kasada, Akamai, Imperva, AWS WAF (detected, not
  solvable in v1), Vercel, and generic HTTP blocks.
- Live sitekey capture from render hooks, widget DOM, and iframes, token
  injection, then reload. `--solve-widgets` handles a widget on a page that
  was never blocked.
- `plague_captcha_demos` runs the public demo walls and classifies the result.

So the gap in the bugger-kit is not capability, it is wiring and policy. The
solver exists; the kit's doctrine currently forbids using it. See section 6.

---

## 1. What OpenCode Browse is

An MCP server plus a Chromium extension that lets an agent drive the user's
real browser, with the user's tabs, cookies, logins, and extensions.

- Opens and drives tabs with Playwright.
- Screenshots, screen recording, and network traffic exported as HAR.
- Agent tabs open in background tabs inside collapsed groups, so they do not
  steal the window.
- **Handoff model**: at a login, a 2FA prompt, or a payment the agent gives the
  tab back, the human completes the step, clicks Continue, and the agent
  resumes.
- **Lend a tab**: a toolbar button hands an already-open tab to the agent.
- **Allowlists**: per-session restriction to named sites.
- Works with any MCP client (OpenCode, Claude Code, Cursor, Codex, Zed).
- Browser targets: Chrome, Edge, Brave, Arc, Helium, Vivaldi, Opera, Chromium.
  Not Firefox, not WebKit.
- Install: Chrome Web Store extension first, then the extension walks through
  the CLI (`@opencode/browse`, or the `curl` and `irm` install scripts).

The design thesis is "real identity, human in the loop". That is the opposite
of an isolated, attributable test identity, and it is the single most important
thing to weigh before adopting it.

## 2. Captcha: Browse does not solve them

No solver, no solving service, no stealth layer, no bypass. Challenges are
handed to the human by design.

The only related effect is indirect and worth naming precisely: a
browser-extension-driven browser is not launched with Playwright's automation
flags, and it carries a genuine profile with real history and real extensions.
That is a convincing fingerprint and can mean fewer challenges. It is "less
likely to be challenged", not "bypass". Do not build a workflow that assumes
it, and do not let it be described as evasion in a report.

**UNVERIFIED**: whether Browse's extension uses `chrome.debugger` or the
Playwright extension bridge, and therefore whether `navigator.webdriver` or
any other CDP artifact remains visible to the page.

## 3. Browse compared with Playwright MCP

Playwright MCP here means Microsoft's `@playwright/mcp`, which is what the
bugger-kit runs as `bh --stealth` (CloakBrowser backend) and `bh --stock`.

### Where Browse is better

| Area | Browse | Playwright MCP |
| --- | --- | --- |
| Profile | Your real Chrome profile by default: cookies, extensions, saved passwords, passkeys, SSO | Its own profile under the ms-playwright cache, empty on first run |
| Human handoff | Explicit "your turn" state, tab handed over, resumes on Continue | A blocked tool call while the agent waits; recovery is up to the model |
| Window behavior | Background tabs in collapsed groups, work continues | Headed mode foregrounds its own window |
| Lend a tab | One click, keeps current URL and state | No equivalent product surface (extension mode has tab selection, less polished) |
| Scope control | Per-session allowlists | None at the product level; prompt or outer sandbox only |
| Recording | Screen recording | Traces and screenshots, no video |
| Setup | Store install and a guided CLI walkthrough, no node toolchain | Needs node, `npx`, and a browser download |
| Browser choice | Seven Chrome-family browsers | Bundled Chromium, Firefox, WebKit; extension mode is Chrome-family only |

The real-profile advantage is the one that matters most in practice. Fresh
automation profiles get hit by Google's "this browser may not be secure" wall,
which is exactly why the bugger-kit has to do the Com Olho Google sign-in
manually. Browse would inherit a profile that is already trusted by the
identity provider.

### Where Playwright MCP is better

- **Accessibility snapshots with stable refs.** Compact, deterministic,
  token-efficient. Browse appears to lean on screenshots and DOM dumps, so
  expect a higher token cost per step for the same action. **UNVERIFIED**,
  depends on the actual tool list.
- **Automation depth.** `browser_evaluate` for page JS, request interception
  and mocking, response body extraction, dialog handling, file upload, PDF,
  programmatic multi-tab control.
- **Isolation.** A throwaway profile is a feature for security testing: one
  identity per engagement, no personal cookies on a target.
- **No store extension with broad host permissions in the daily browser.**
- **Firefox and WebKit** when engine behavior differs.
- **CDP attach** to a remote or containerized browser.

Summary: Browse is a better operator experience, Playwright MCP is a better
test instrument.

## 4. Browse compared with Plague

They overlap less than they appear to.

| Dimension | Plague | Browse |
| --- | --- | --- |
| Core job | Fetch, classify, fingerprint, escalate across three tiers | Interactive control of a live tab |
| Output | Text, optional HTML, cookies, attempt timeline | DOM, screenshots, video, HAR, click and type |
| Speed and cost | 71 ms warm p50 per README, no rendering for clean pages | Full render per step, screenshot heavy |
| Challenge handling | Detector plus solver plus injection, or an honest "cannot solve" | Human handoff |
| Identity | Engagement profile, or CloakBrowser's stealth build | Your daily profile |
| Scope | Router policy, per-request | Product allowlists |
| MCP tools | `plague_doctor`, `plague_fetch`, `plague_detect`, `plague_fingerprint`, `plague_bench`, `plague_captcha_demos` | Unknown full list, **UNVERIFIED** |

Plague explicitly cannot click, type, or manage tabs. Browse does nothing else.
They are complements: the natural split is Plague for recon, classification,
and bulk fetch, Browse or a Playwright family for flows that need a live page.

The honest limitation on the Plague side, already in its README: risk-score
systems cannot be bought out. DataDome, Kasada, and PerimeterX score your TLS
and behavior, and a solved token does not fix a bad fingerprint. Browse's real
profile is genuinely strong there, which is an argument for Browse on those
specific pages and not an argument for a solver subscription.

## 5. Can Browse drive CloakBrowser?

Probably not directly.

- Browse's extension attaches to an installed Chrome-family browser.
- CloakBrowser is a separate patched Chromium launched from Python through
  `cloakbrowser.launch_persistent_context`.

Those are different binaries with different launch paths. Composing them needs
one of: a Browse CLI option for executable and profile directory, a way to
point the extension at an already-running Chromium over a debug port, or a
CloakBrowser build registered as the default Chrome. **UNVERIFIED**: the
Browse CLI may expose a profile directory, and the extension may accept a
remote browser over CDP, but that has to be read out of the source and tested.

If it turns out the extension only attaches to an installed browser, the
combination "Browse plus CloakBrowser" is not a thing, and choosing Browse
means choosing a real profile instead of a stealth build.

## 6. Implications for the bugger-kit

### The profile question is the blocker

The kit keeps three identities apart on purpose:

- engagement browser profile `./.playwright-profile` (Plague receives it as
  `PLAGUE_PROFILE_DIR`);
- platform profile `~/.config/bugger-kit/browser/platforms`, so HackerOne and
  Bugcrowd sessions survive across engagements;
- and an explicit rule that target cookies never mix with platform cookies
  (`README.md:258-262`, `267-269`).

Browse collapses all three into the daily browser. That is an evidence
integrity and OPSEC problem, not a convenience tradeoff.

### The doctrine question is the other blocker

The kit says "escalate, do not bypass" in several places, and a solver hookup
would contradict all of them:

- `skills/tooling/SKILL.md:46` "WAF / bot protection (escalate, do not bypass)"
- `skills/tooling/SKILL.md:54-55` "Never use stealth to defeat a block the
  program wants in place."
- `skills/tooling/SKILL.md:63` "never defeat a deliberate bot challenge"
- `README.md:263-266` "Stealth is not a WAF bypass tool... never used to evade
  anti-bot protection a program deliberately enforces."
- `skills/reporting/references/submission-assist.md:33` "never bypasses a WAF"

Meanwhile the kit already has the manual path that works: `bin/session login`
opens a headed CloakBrowser window and waits at "finish MFA/captcha". Most
programs put the wall on registration or login, and after one manual login the
session is exported to curl with `session export`, `jar`, and `use`, where the
API has no captcha at all. The marginal value of automated solving is small
and the rule risk is high.

### Scope and audit plumbing

Every kit fetch is gated by `bin/scope` through `safe-request`,
`browser-request`, and reconciled by `audit-traffic`. Browse navigates with no
scope check, and its allowlists are per session rather than derived from
`INSTRUCTIONS.md`. Any adoption needs a mapping from the scope block to the
allowlist, or the kit loses its main safety property.

HAR is also a leak vector: HAR from a daily profile contains live session
cookies and auth headers, and the kit's pre-commit guard only matches values
from `secrets/`. If Browse is ever used, scrub HAR before it lands in
`artifacts/`.

### Token cost

`bin/platforms grab` exists specifically so intake "costs no browser-tool
tokens" (`README.md:232-234`). Screenshot-driven automation is the expensive
end of that spectrum. Prefer Plague text fetches for anything that does not
need interaction.

## 7. Open questions to verify in source

Checklist for `github.com/anomalyco/browse`:

- [ ] Full MCP tool list and their inputs, especially whether reads are
      accessibility snapshots or screenshots.
- [ ] Whether the CLI and extension talk only to localhost, or phone home.
- [ ] Extension host permissions, requested at install and used at runtime.
- [ ] Whether the CLI accepts a profile directory, and whether it accepts an
      executable path (decides section 5).
- [ ] Whether the extension can attach to an already-running browser over CDP.
- [ ] HAR output: which headers are included, and whether cookies can be
      excluded.
- [ ] Whether allowlists are enforced in the extension or only in the MCP
      server (enforcement location determines whether they are real).
- [ ] Whether background tabs are included in the toolbar's "lend" list when
      they belong to other profiles.
- [ ] License terms for commercial use, if a client engagement needs it.

## 8. Suggested next steps, in order of value

1. **Expose the existing solver to the kit, behind an explicit gate.** Plague
   already solves; the bugger-kit just never calls it. Gate it on a recorded
   `ROE: automation allowed` line in `INSTRUCTIONS.md` and an opt-in flag, and
   log every solve attempt as an `INTEL` line with provider, vendor, cost, and
   outcome. Never on by default.
2. **`session login --url`.** Two hours of work: open headed, pre-navigate to
   the challenged page, save storage state on Enter. Removes the friction that
   makes people ask for a solver in the first place.
3. **Challenge classifier rule for the agent.** If the page matches a challenge
   marker, stop and hand off instead of retrying. `platforms` and
   `submit-assist` already carry `CHALLENGE_MARKERS`; the agent prompt does not
   use them as a stop condition.
4. **Only then consider Browse**, as a narrow opt-in for platform work (the
   Google-sign-in case) on a dedicated Chrome profile, allowlisted to the
   platform domains, never on target hosts.
5. **Do not** point a solver at risk-score vendors. Plague's README already
   says it cannot work; the money is better spent on the stealth tier.

## 9. One-line summary

Browse is the best human-in-the-loop browser product available and the wrong
default identity for a bug bounty kit. Plague already has the solver, and the
interesting engineering is the gate and the audit trail, not the solver call.
