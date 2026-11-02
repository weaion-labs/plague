# Benchmarks

Two independent measurements:

- `bench_speed.py`: cold and warm navigation, extraction accuracy, memory, and
  optional concurrency on local deterministic pages.
- `bench_detection.py`: offline challenge-detection accuracy over labeled
  synthetic pages.

## Run

```bash
python benchmarks/bench_speed.py --repeat 3
python benchmarks/bench_speed.py --repeat 3 --concurrency 3
python benchmarks/bench_speed.py --quick
python benchmarks/bench_detection.py
```

Results are written to `out/speed.json` (or `--json`).

## Speed, local pages

Four pages, twelve extraction checks, `--repeat 3`. Times in milliseconds.

| Engine | Cold mean | Warm mean | Warm p50 | Warm p95 | Accuracy | RSS |
|---|---:|---:|---:|---:|---:|---:|
| lightpanda-patched | 1144 | 124 | 71 | 329 | 100% | 155 MB |
| lightpanda-stock | 1123 | 117 | 69 | 323 | 100% | 149 MB |
| cloak | 778 | 122 | 84 | 316 | 100% | 848 MB |
| chrome | 943 | 118 | 72 | 303 | 100% | 1052 MB |
| playwright-chromium | 255 | 120 | 67 | 318 | 100% | 572 MB |

Per-page warm means:

| Engine | clean 1 | clean 2 | JS hydration | 180 KB page |
|---|---:|---:|---:|---:|
| lightpanda-patched | 60 | 73 | 329 | 36 |
| lightpanda-stock | 46 | 61 | 323 | 38 |
| cloak | 39 | 57 | 308 | 86 |
| chrome | 48 | 45 | 304 | 76 |
| playwright-chromium | 28 | 64 | 318 | 68 |

The JS page includes a 250 ms settle wait in every engine, so its number is
mostly the wait, not engine work.

Concurrency with three sessions, one run:

| Engine | Wall time | RSS |
|---|---:|---:|
| lightpanda-patched | 2564 ms | 444 MB |
| lightpanda-stock | 1148 ms | 434 MB |
| cloak | 928 ms | 2450 MB |
| chrome | 1203 ms | 2914 MB |

The patched Lightpanda concurrency number was an outlier in this run. Its
memory number is the stable and important one: about 148 MB per session.

## What the numbers mean

- **Cold one-shot fetch:** raw Playwright wins. Plague with Lightpanda pays about
  one second of process startup. The router's normal `fetch()` is cold.
- **Warm navigation:** all engines land around 120 ms mean and 70 ms p50 on
  small local pages. Lightpanda is not dramatically faster there.
- **Large content:** Lightpanda is about twice as fast as Chrome because it does
  not build a layout tree.
- **Memory:** Lightpanda uses about 150 MB versus 850 MB for Cloak and 1050 MB
  for Chrome. Three Lightpanda sessions fit in 444 MB; three Chrome sessions
  need about 2.9 GB.
- **Accuracy:** 100% on the local checks, including JS hydration, for every
  engine.
- **Challenge detection:** 20 labeled cases, 100% vendor, blocking, and solvable
  accuracy, with 100% blocking precision and recall.

## Practical recipe

- One page, visual output, or a CAPTCHA widget: use Chrome or Cloak.
- Many pages, mostly clean: use a warm Lightpanda session.
- Mixed: use Lightpanda warm for the bulk, `plague detect` on the odd page, and
  escalate only when a wall appears.
- Use `plague bench --warm --tier fast URL...` to measure a real target list
  with one reused session.

Warm mode skips escalation by design. If a page in the list hits a wall, it is
reported, not retried on Cloak.

## Files

- `server.py`: local pages and challenge fixtures.
- `bench_speed.py`: cold, warm, accuracy, memory, concurrency.
- `bench_detection.py`: detector precision and recall.
