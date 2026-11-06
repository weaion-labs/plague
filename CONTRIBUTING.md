# Contributing

Thanks for taking a look. Plague is small on purpose: one router, three
engines, and a clear benchmark.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
playwright install chromium
plague doctor
```

Lightpanda is optional for development. Install the nightly binary with:

```bash
plague doctor --install
```

CloakBrowser downloads on first launch. The free build is enough for local
work.

## Tests

```bash
python -m pytest                 # unit tests, no browsers
python -m pytest -m integration  # real Chromium and MCP tests
python benchmarks/bench_detection.py
```

Please keep the unit suite browser-free and fast. Any test that starts a
browser belongs in the `integration` marker.

## Benchmarks

If a change touches the engines, the router, or extraction, include before and
after numbers:

```bash
python benchmarks/bench_speed.py --repeat 3
python benchmarks/bench_speed.py --repeat 3 --concurrency 3
```

State the machine and the page set. Do not compare a warm run against a cold
run. Do not tune one engine and leave the others default.

## Pull requests

- Keep the change focused.
- Add or update tests.
- Update the README or `benchmarks/README.md` if behavior changes.
- Do not include credentials, cookies, target-specific bypass recipes, or
  personal data.
- Run `python -m compileall -q plague tests scripts benchmarks examples`.

## Scope and legal

Plague is a routing and instrumentation tool. Contributions should stay
general. Do not add site-specific bypass flows, credential harvesting, or
automation aimed at a named third-party service without permission.

## Contact

hello@weaionlabs.com
