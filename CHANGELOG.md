# Changelog

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
