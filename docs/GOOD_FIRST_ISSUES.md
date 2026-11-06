# Good first issues

Draft issues for the GitHub repo. Create them as Weaion Labs, not a personal
account. Use the `good first issue` and `help wanted` labels.

## 1. Add a Docker image for the MCP server and Lightpanda

Scope:

- Multi-stage Dockerfile with Python, the project, and the Lightpanda nightly.
- No Cloak or Chrome in the image; document that the stealth tier runs on the
  host.
- Publish to GHCR on release.
- Add a `docker run` example to the README.

Acceptance:

- `docker run --rm -i ghcr.io/weaion-labs/plague-mcp` starts the MCP server.
- The image is under 500 MB.
- CI builds the image on pull requests.

## 2. Add a real-world benchmark set

Scope:

- 100 public pages from Wikipedia, Hacker News, and a documentation site.
- Measure success rate, warm p50, p95, and memory.
- Record engine and challenge per page.
- Commit a JSON result and a short report in `benchmarks/`.

Acceptance:

- The scripts are reproducible.
- The report explains failures, not only successes.
- The README links to the report.

## 3. Add Crawlee and Scrapling examples

Scope:

- One example each in `examples/integrations/`.
- Use the warm batch API or a CDP connection.
- Document when to use Plague versus the framework's own browser pool.

Acceptance:

- Examples run against the local benchmark server.
- No target-specific bypass flows.

## 4. Add a network fingerprint command

Scope:

- `plague fingerprint --network` fetches a TLS fingerprint endpoint and prints
  JA4, JA4 cipher hash, and the Akamai HTTP/2 hash.
- Compare the active engine against a saved Chrome baseline.
- Show the four known extension gaps without failing.

Acceptance:

- Works for Lightpanda, Cloak, and Chrome.
- The output is JSON with `--json`.
- The README documents the command.

## 5. Add Windows and WSL setup notes

Scope:

- Lightpanda has no native Windows binary.
- Document WSL2, the glibc requirement, and the Playwright install.
- Add a troubleshooting section for missing fonts and display errors.

Acceptance:

- A clean Windows machine with WSL2 can follow the guide.
- No steps require a personal account.

## 6. Auto-cap workers by tier

Scope:

- `plague batch` should warn when `--workers` is too high for Chrome or Cloak.
- Suggest a cap based on available memory.
- Keep `--workers` explicit; do not silently reduce it.

Acceptance:

- A warning appears for 4 workers on Chrome or Cloak.
- The warning includes the estimated memory.
- Tests cover the warning helper.
