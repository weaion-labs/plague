# v0.1.0

Plague is a tiered browser router: Lightpanda first for speed, CloakBrowser when
a wall appears, stock Chrome for reference and visual work.

## Highlights

- One API for three engines, with capability filtering and escalation.
- Chrome persona build of Lightpanda with matching client hints, TLS cipher set,
  and HTTP/2 fingerprint.
- Challenge detection for Cloudflare, Turnstile, reCAPTCHA v2 and v3, hCaptcha,
  DataDome, PerimeterX, Kasada, Akamai, Imperva, AWS WAF, and Vercel.
- CapSolver, 2Captcha, and manual token solving.
- Warm batch mode: one session per worker, optional escalation.
- Project-local MCP server with fetch, detect, fingerprint, bench, doctor, and
  CAPTCHA demo tools.

## Benchmarks

Local deterministic pages, repeat 3:

| Engine | Cold fetch | Warm p50 | Accuracy | RSS |
|---|---:|---:|---:|---:|
| Lightpanda patched | 1144 ms | 71 ms | 100% | 155 MB |
| Chrome | 943 ms | 72 ms | 100% | 1052 MB |
| Playwright Chromium | 255 ms | 67 ms | 100% | 572 MB |

The full methodology is in `benchmarks/README.md`. The short version: raw
Playwright wins a single cold fetch, Lightpanda wins on memory and large content
pages, and warm batch mode is the fast path for a list of pages.

## Install

```bash
pip install -e .
playwright install chromium
plague doctor --install
plague doctor
```

The PyPI package is `plague-browser`. Publishing is documented in
`docs/PUBLISHING.md`.

## Limitations

- Canvas and WebGL are not implemented in Lightpanda. WebRTC is absent.
- Four TLS extensions still differ from Chrome: `001b`, `0023`, `44cd`, `fe0d`.
- No tool bypasses every CAPTCHA. Risk engines are a fingerprint and IP problem,
  not a token problem.
- The free headless Cloak build still fails the NopeCHA Cloudflare demo.

## Links

- Repository: https://github.com/weaion-labs/plague
- Benchmarks: `benchmarks/README.md`
- Reverse engineering notes: `docs/REVERSE_ENGINEERING.md`
- MCP server: `plague/mcp_server.py`
