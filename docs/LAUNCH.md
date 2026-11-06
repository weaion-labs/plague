# Launch kit

Use Weaion Labs accounts. Do not post from a personal account.

## One-line pitch

```text
CloakBrowser stealth. Lightpanda speed. One browser router.
```

## Longer pitch

```text
Plague routes each page to the cheapest browser that can handle it. Clean pages
go to a patched Lightpanda with a Chrome network fingerprint. Walls escalate to
CloakBrowser. Visual work goes to Chrome. Warm batch mode is about 7x lighter
than Chrome on memory.
```

## Storefront checklist

- [ ] Upload `assets/social-preview.png` in GitHub repository settings.
- [ ] Add the repo to the Weaion Labs org profile as a featured project.
- [ ] Create the `v0.1.0` release with `RELEASE_NOTES_v0.1.0.md`.
- [ ] Publish `plague-browser` to PyPI with trusted publishing.
- [ ] Add the PyPI badge and `pip install plague-browser` to the README.
- [ ] Add the benchmark images to the README speed section.
- [ ] Submit to the MCP directories using `docs/MCP_PUBLISHING.md`.
- [ ] Add topics: browser automation, scraping, playwright, lightpanda,
  cloakbrowser, mcp, captcha, stealth browser.

## Show HN

Title:

```text
Show HN: Plague - a browser router that sends clean pages to Lightpanda
```

Body:

```text
I built a router around three browsers instead of pretending one can do
everything.

Lightpanda is fast and cheap, but it has no real canvas, WebGL, or layout. Chrome
is compatible but heavy. CloakBrowser is a patched Chromium that passes harder
fingerprint checks, but it costs Chrome-level memory.

Plague sends clean pages to a patched Lightpanda with a Chrome User-Agent,
client hints, TLS cipher set, and HTTP/2 fingerprint. If a wall appears, it
escalates to CloakBrowser. Visual work goes to Chrome. Warm batch mode reuses
one session per worker.

The honest benchmark: raw Playwright wins a single cold fetch because Lightpanda
pays about a second of startup. Warm, Lightpanda is comparable on small pages,
about 2x faster on a 180 KB content page, and about 7x lighter on memory.

The repo includes the benchmark scripts, a challenge detector, token solvers, a
project-local MCP server, and the reverse engineering notes. The limitations are
documented. Canvas and WebGL are still missing, and four TLS extensions differ
from Chrome.

I would like feedback on the routing policy and on real-world page sets.
```

## Reddit r/webscraping

Title:

```text
Benchmarked Lightpanda vs Chrome vs CloakBrowser on the same pages
```

Body: use the Show HN body, but lead with the benchmark table and link to
`benchmarks/README.md`.

## LinkedIn

```text
We built Plague: a router between Lightpanda speed and CloakBrowser stealth.

Cold one-shot, Playwright is faster. Warm batch, Lightpanda is comparable on
small pages, about 2x faster on large content, and about 7x lighter on memory.

One API. Three engines. The limitations are documented, including the missing
canvas and WebGL surfaces.

Code, benchmarks, and MCP server:
https://github.com/weaion-labs/plague
```

## X

```text
Plague: CloakBrowser stealth. Lightpanda speed. One router.

71 ms warm p50
155 MB per session
2x faster on large pages
100% on the local extraction suite

Benchmarks, MCP server, and the honest limitations:
https://github.com/weaion-labs/plague
```

## 30 day plan

| Week | Work |
|---|---|
| 1 | Social preview, release, PyPI, README badges, org profile feature |
| 2 | MCP directories, issue templates, contributing guide |
| 3 | Benchmark post, Show HN, Reddit, LinkedIn, X |
| 4 | Integrations, newsletters, follow-up with real user numbers |

## Rules

- Do not claim "bypasses all CAPTCHAs."
- Do not buy stars or downloads.
- Do not spam unrelated communities.
- Always include the cold-start caveat. The honesty is the differentiator.
- Use UTM links so you can see which channel converts.
