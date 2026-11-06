# The fast browser is not always the quick one

We benchmarked Lightpanda, Chrome, and CloakBrowser on the same pages. The
result is less convenient than the marketing:

- A single cold fetch is fastest in raw Playwright.
- Warm navigation is roughly tied on small pages.
- Lightpanda wins on large content pages and memory by a wide margin.
- CloakBrowser is the one to use when the page fights back.

That is why Plague is a router, not a new browser.

## The problem

Lightpanda is a headless browser written in Zig. It executes JavaScript, has no
layout engine, and uses far less memory than Chromium. It is excellent for
reading pages at scale.

It is not Chrome. It has no real canvas, no WebGL, no WebRTC, and a smaller API
surface. A serious anti-bot system can see that.

CloakBrowser is the opposite trade. It is a patched Chromium with source-level
fingerprint changes. It walks like Chrome because it is Chrome. It also costs
Chrome memory and startup time.

Most scraping stacks pick one and then write glue around its weaknesses. We
wanted the glue to be the product.

## What Plague does

Plague sends each page to the cheapest browser that can handle it:

1. Try the patched Lightpanda.
2. If a wall appears, close the session and retry on CloakBrowser.
3. Use stock Chrome for reference, visual checks, and debugging.

The patched Lightpanda is the interesting part. It reports a Chrome 146 Windows
User-Agent, Chrome client hints, `Win32`, `Google Inc.`, five PDF plugins, and a
1920x1080 screen. It matches Chrome's TLS cipher set and, with the bundled curl
patch, the full Akamai HTTP/2 fingerprint.

It is still not Cloak. The full JA4 string differs by four extensions, and
canvas, WebGL, and WebRTC are missing. We document that instead of hiding it.

## Methodology

All numbers below are from local deterministic pages and the scripts in
`benchmarks/`. Four pages:

- two clean HTML pages
- one JavaScript hydration page
- one 180 KB content page

Twelve extraction checks. `--repeat 3`. The machine is a 16-core Linux box with
16 GB of RAM. Times are milliseconds. Memory is process tree RSS for one warm
session.

The benchmark measures the engine, not the network. That is deliberate. Network
latency varies too much to compare engines fairly.

## Cold fetch

| Engine | Cold mean |
|---|---:|
| Playwright Chromium | 255 ms |
| CloakBrowser | 778 ms |
| Chrome | 943 ms |
| Lightpanda patched | 1144 ms |

This is the number that hurts. Lightpanda pays about one second of process
startup. Raw Playwright is four times faster for a single page.

If your job is one page, use Playwright. Do not use a router to make a single
fetch slower.

## Warm navigation

| Engine | Warm mean | Warm p50 | RSS |
|---|---:|---:|---:|
| Lightpanda patched | 124 ms | 71 ms | 155 MB |
| Chrome | 118 ms | 72 ms | 1052 MB |
| CloakBrowser | 122 ms | 84 ms | 848 MB |
| Playwright Chromium | 120 ms | 67 ms | 572 MB |

Warm, the engines are close on small pages. Lightpanda is not magic. It is
simply cheap.

The interesting column is memory. One Lightpanda session uses about 155 MB.
Chrome uses about 1 GB. Three Lightpanda workers fit in 444 MB. Three Chrome
workers needed about 2.9 GB.

That is the scale argument. If you run ten workers, the difference is the
machine you have to rent.

## Large content

On the 180 KB page, warm Lightpanda averaged 36 ms. Chrome averaged 76 ms.
Lightpanda has no layout tree to build, so large text extraction is roughly
twice as fast.

This is where the fast engine earns its place. Not tiny pages. Large content,
many pages, tight memory.

## Accuracy

All engines passed the twelve extraction checks, including the JavaScript
hydration page. The challenge detector passed twenty labeled cases with 100%
blocking precision and recall.

The detector is conservative on purpose. A reCAPTCHA widget on a contact form is
not a block. A page is only treated as blocked when a mitigation header says so,
the status is hostile, an interstitial phrase is present, or the URL looks like
a challenge endpoint.

## What still blocks

The NopeCHA Cloudflare demo still blocks the free headless Cloak build. A newer
paid Cloak build, a headed window, and a residential IP are the levers for that
class of target.

`www.canada.ca` still returns an HTTP/2 stream error on both stock and patched
Lightpanda. Cipher and HTTP/2 now match Cloak, so the remaining Akamai signal is
elsewhere.

No tool bypasses every CAPTCHA. Token walls can be solved. Risk engines are a
fingerprint, IP, and behavior problem. If a vendor promises otherwise, they are
selling a demo.

## Reproduce

```bash
git clone https://github.com/weaion-labs/plague
cd plague
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

python benchmarks/bench_speed.py --repeat 3
python benchmarks/bench_detection.py
```

The full tables and caveats are in `benchmarks/README.md`.

## The takeaway

The fast browser is not always the quick one. Startup, page size, memory, and
the target's defenses all change the answer.

Plague makes the routing explicit: fast path, stealth path, reference path. It
shows the cost of each choice in the benchmark and in the result.

If that trade is useful to you, star the repo and tell us which page set you
want measured next.

https://github.com/weaion-labs/plague
