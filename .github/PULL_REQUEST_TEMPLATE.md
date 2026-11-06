## Summary

Describe the change and why it belongs in Plague.

## Tests

- [ ] `python -m pytest`
- [ ] `python -m pytest -m integration` (if a browser or MCP path changed)
- [ ] `python benchmarks/bench_detection.py` (if detection changed)

## Benchmarks

If this touches an engine, the router, or extraction, include before and after
numbers from `benchmarks/bench_speed.py`. State the machine and whether the
run was cold or warm.

## Checklist

- [ ] The change is focused.
- [ ] No credentials, cookies, personal data, or target-specific bypass flows.
- [ ] README or benchmarks documentation updated when behavior changes.
- [ ] `python -m compileall -q plague tests scripts benchmarks examples` passes.
