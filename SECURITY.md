# Security policy

## Supported versions

The `0.1.x` line receives security fixes.

## Reporting a vulnerability

Do not open a public issue for a security problem. Email:

```text
hello@weaionlabs.com
```

Include the affected version, a minimal reproduction, and the impact. You will
get an acknowledgement within five business days.

## Scope

In scope:

- command injection through URLs, selectors, proxy settings, or MCP tool input
- credential or cookie leaks in logs, results, or MCP responses
- token handling in the solver and injection paths
- unsafe defaults in `plague serve` or the MCP server

Out of scope:

- CAPTCHA vendor behavior or a site changing its anti-bot rules
- a target blocking the browser
- vulnerabilities in Chrome, Chromium, CloakBrowser, or Lightpanda itself
  (report those upstream)

## Operational note

The MCP server and `plague serve` expose browser control. Bind them to
localhost unless you add authentication and network controls. Never expose a
CDP port to the public internet.
