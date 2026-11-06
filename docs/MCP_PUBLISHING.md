# MCP publishing kit

Use Weaion Labs accounts for every directory. Do not submit from a personal
account.

## Listing copy

Name:

```text
Plague
```

Short description:

```text
CloakBrowser stealth, Lightpanda speed. One browser router with fetch, detect,
fingerprint, and benchmark tools for agents.
```

Long description:

```text
Plague routes each page to the cheapest browser that can handle it. Clean pages
go to a patched Lightpanda with a Chrome network fingerprint. Blocked pages
escalate to CloakBrowser. Visual work goes to Chrome. The MCP server exposes
fetch, detect, fingerprint, bench, doctor, and CAPTCHA demo tools, plus the
reverse engineering notes as a resource.
```

Repository:

```text
https://github.com/weaion-labs/plague
```

Install after PyPI publishing:

```bash
pip install plague-browser
python -m plague.mcp_server
```

Install from a clone today:

```bash
git clone https://github.com/weaion-labs/plague
cd plague
python -m plague.mcp_server
```

## Local MCP config

```json
{
  "mcpServers": {
    "plague": {
      "command": "python3",
      "args": ["-m", "plague.mcp_server"],
      "cwd": "/path/to/plague",
      "env": {
        "PLAGUE_LIGHTPANDA_BIN": "/path/to/plague/.plague/lightpanda-src/zig-out/bin/lightpanda"
      }
    }
  }
}
```

## Tools

- `doctor`: engine availability, solver, binary paths.
- `fetch`: one URL through the router.
- `detect`: classify a challenge without solving.
- `fingerprint`: compare navigator, screen, client hints, and canvas.
- `bench`: warm batch with workers and optional escalation.
- `captcha_demos`: run the public demo walls.

## Resources

- `plague://docs/reverse-engineering`
- `plague://docs/readme`

## Directories

Submit the repository with the listing copy above:

- Smithery: https://smithery.ai
- mcp.so: https://mcp.so
- Glama: https://glama.ai/mcp/servers
- PulseMCP: https://www.pulsemcp.com
- awesome-mcp-servers: open a PR with the repo URL and one-line description

Glama and some indexes crawl GitHub automatically. A clean README with the MCP
section and a `server.json` or directory form is enough for the manual ones.

## Security

The server exposes browser control. Keep it local. Do not expose it on a public
interface without authentication and network controls. See `SECURITY.md`.
