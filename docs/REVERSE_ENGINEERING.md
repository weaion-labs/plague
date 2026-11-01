# Reverse engineering notes: CloakBrowser vs Lightpanda

Date: 2026-11-02

This document records what was inspected, what could be ported, and what could
not. It is deliberately blunt: the goal was a real comparison, not a demo.

## CloakBrowser

- Binary: `/home/taj/.cloakbrowser/chromium-146.0.7680.177.5/chrome`
- Size: 444 MB, ELF x86-64, not stripped
- Version: Chromium 146.0.7680.177.5
- Build: clang 23 / Rust 1.95 toolchain strings, Chromium build flags
- Wrapper: Python/JS packages around the binary, no patch source in the repo

What the wrapper and changelog expose:

- 58 source-level patches in the free 146 build; the current Pro build has more
- Canvas, WebGL, WebGPU, audio, fonts, GPU, screen, WebRTC, network timing,
  storage quota, WebAuthn, AAC, window position, automation signals, and CDP
  input behavior are all named in the changelog
- Flags such as `--fingerprint=<seed>`, `--fingerprint-platform`,
  `--fingerprint-noise`, `--fingerprint-webrtc-ip`, and
  `--fingerprint-allow-3p-cookies`

What the binary itself shows:

- `nm -C` finds Chromium symbols such as `compute_fingerprint_id`,
  `create_fingerprint_context`, and `fingerprint_cache_*`, plus the normal Blink
  `WebdriverAttributeGetCallback`
- The custom `--fingerprint-*` strings are not present as plain strings in the
  binary, so the flag parser is either generated, obfuscated, or stored in a
  form `strings` does not show
- No Cloak-specific symbol prefix was found. The patches are compiled into
  Chromium and are not separable as a library or patch file

Conclusion: Cloak is a real Chromium build with source-level modifications. The
patch source is not public. There is nothing to `git apply` onto another
browser, and the modified functions live inside Blink, Skia, the GPU stack, and
the network stack.

## Lightpanda

- Binary: Zig, stripped, about 74 MB
- Engine: Zig + V8, html5ever, libcurl, BoringSSL, nghttp2
- Rendering: no Blink, no Skia, no compositor; a Rust `tiny-skia` + `parley`
  renderer exists for page dumps and screenshots
- Canvas 2D: API surface exists, but `fillRect`, `fillText`, and friends only
  mark `canvas2d` as unsupported. `getImageData` returns a blank `ImageData`
- WebGL: the context is not created (`canvas.getContext("webgl")` returns null)
- WebAudio: a real graph implementation exists
- Network: libcurl with BoringSSL, so the TLS library is the same family as
  Chrome. The ClientHello configuration is not Chrome's

## Empirical diff, stock build

Probe page: `https://example.com`, headless.

| Property | Lightpanda | CloakBrowser |
|---|---|---|
| User-Agent | `Lightpanda/1.0` (empty in one CLI run) | Chrome 146 Windows |
| `navigator.platform` | `Linux x86_64` | `Win32` |
| `navigator.vendor` | empty | `Google Inc.` |
| `navigator.plugins` | 0 | 5 |
| `navigator.mimeTypes` | 0 | 2 |
| `window.chrome` | undefined | object |
| `hardwareConcurrency` | 4 | 8 |
| `deviceMemory` | 8 | 8 |
| `screen` | 1280x720 | 1920x1080 |
| Canvas pixel after fill | `[0,0,0,0]` | `[255,102,0,255]` |
| WebGL context | null | null (headless) |
| `RTCPeerConnection` | undefined | function |
| `navigator.userAgentData` | Lightpanda brands | Chrome brands |
| Timezone | host | host |

The WebGL result is not a difference in this environment: both return null in
headless mode. On a headed Cloak session WebGL may exist, but that is a
different comparison.

## What was ported

The port is a reimplementation inside Lightpanda's own architecture, not a copy
of Cloak's binary patches.

1. `src/Config.zig`
   - Chrome 146 Windows User-Agent as the default
   - Chrome brand list for `Sec-CH-UA` and `navigator.userAgentData.brands`
   - Removed the "Mozilla" rejection from `--user-agent`
   - Removed the matching CDP rejection path by allowing the UA through
2. `src/browser/webapi/Navigator.zig`
   - `appVersion` -> Chrome 146 Windows app version
   - `platform` -> `Win32`
   - `vendor` -> `Google Inc.`
   - `hardwareConcurrency` -> 8
3. `src/browser/webapi/NavigatorUAData.zig`
   - platform -> `Windows`
   - platform version -> `19.0.0`
   - major versions in `brands`, full versions in `fullVersionList`
4. `src/browser/frame/persona.js` + `src/browser/frame/node_factory.zig`
   - built-in script evaluated in every document realm before page scripts
   - plugins, mimeTypes, pdfViewerEnabled, connection
   - `window.chrome`
   - screen and window dimensions
   - no canvas or WebGL faking, on purpose
5. `src/network/HttpClient.zig`
   - ignores an empty User-Agent override instead of blanking the UA
   - `Sec-Ch-Ua-Mobile` and `Sec-Ch-Ua-Platform` baseline headers
6. `src/network/http.zig` + `src/sys/libcrypto.zig`
   - Chrome TLS cipher list
   - Chrome curve list by default
   - GREASE, OCSP stapling, SCT, extension permutation
7. bundled libcurl, `patches/curl-http2-chrome.patch`
   - Chrome HTTP/2 SETTINGS, stream and connection windows
   - Chrome pseudo-header order `:method`, `:authority`, `:scheme`, `:path`

The persona script runs in the browser process, not through Playwright's
`add_init_script`, so it is part of the build and applies to every frame.

## Final fingerprint, patched build

| Property | Patched Lightpanda | CloakBrowser |
|---|---|---|
| User-Agent | Chrome 146 Windows | Chrome 146 Windows |
| `navigator.platform` | `Win32` | `Win32` |
| `navigator.vendor` | `Google Inc.` | `Google Inc.` |
| plugins | 5 PDF plugins | 5 PDF plugins |
| mimeTypes | 2 | 2 |
| `window.chrome` | object | object |
| `hardwareConcurrency` | 8 | 8 |
| `deviceMemory` | 8 | 8 |
| screen | 1920x1080 | 1920x1080 |
| `navigator.userAgentData` | Chrome brands, Windows | Chrome brands, Windows |
| Canvas pixel after fill | `[0,0,0,0]` | `[255,102,0,255]` |
| WebGL | null | null (headless) |
| `RTCPeerConnection` | undefined | function |
| Timezone | host | host |

Canvas, WebGL, and WebRTC are the remaining browser-level gaps.

## Network fingerprint

| Signal | Patched Lightpanda | CloakBrowser |
|---|---|---|
| JA4 | `t13d1512h2_8daaf6152771_ebb265cc0ce3` | `t13d1516h2_8daaf6152771_d8a2da3f94cd` |
| JA4 cipher hash | `8daaf6152771` | `8daaf6152771` |
| Akamai HTTP/2 text | `1:65536;2:0;4:6291456;6:262144|15663105|0|m,a,s,p` | same |
| Akamai HTTP/2 hash | `52d84b11737d980aef856699f885ca86` | same |

The cipher set and the entire HTTP/2 fingerprint now match. The JA4 extension
set is still four short: `001b` (compress_certificate), `0023`
(extended_master_secret), `44cd` (GREASE), and `fe0d` (ECH).

## CAPTCHA demo matrix, patched auto tier

| Demo | Result |
|---|---|
| `nopecha.com/demo/cloudflare` | fail after about 19s; Lightpanda escalates, Cloak still blocked |
| `nopecha.com/demo/turnstile` | Lightpanda 200, Turnstile widget non-blocking |
| `nopecha.com/demo/recaptcha` | Lightpanda 200, reCAPTCHA widget non-blocking |
| `2captcha.com/demo/recaptcha-v2` | Lightpanda 200, DataDome script non-blocking |

No solver keys were configured, so token walls were detected and classified but
no live solve was purchased. The local integration tests prove the injection
path for reCAPTCHA, hCaptcha, and Turnstile against a real browser.

`www.canada.ca` still fails with `Http2Stream` on both stock and patched
builds. Cipher and HTTP/2 now match Cloak, so the remaining Akamai signal is
elsewhere: likely the TLS extension set, header order, or an Akamai rule.

## What was not ported, and why

- **Canvas 2D**: the native API is a stub. Making `getImageData` return plausible
  pixels means implementing a rasterizer, path filling, text shaping, and font
  metrics. The Rust renderer already uses `tiny-skia` and `parley`, but it
  renders a DOM tree, not canvas commands. Wiring those together is a separate
  project. Random noise would be worse than blank because it would contradict
  any real drawing.
- **WebGL and WebGPU**: no context and no GPU stack. A JavaScript stub is easy
  to detect and provides no real rendering.
- **Fonts**: the page renderer has fontique, but canvas text metrics are stubbed,
  so the usual canvas font fingerprint cannot be made coherent.
- **WebRTC**: no `RTCPeerConnection`. A fake constructor without real ICE
  behavior is a liability.
- **TLS extension set**: the cipher set and HTTP/2 fingerprint now match Cloak.
  The JA4 extension hash still differs because four extensions are missing:
  `001b` (compress_certificate), `0023` (extended_master_secret), `44cd`
  (GREASE), and `fe0d` (ECH). `001b` needs certificate compression callbacks,
  `0023` has no exposed BoringSSL configuration in this build, and `44cd` and
  `fe0d` are GREASE/ECH values the prebuilt library does not emit. Exact JA3
  also differs because extension order is permuted per connection.
- **Behavioral humanization**: Cloak's `humanize=True` is a wrapper-level mouse
  and keyboard model. Lightpanda has no layout, so the same model does not map.

## Licensing

Lightpanda is AGPL-3.0. A modified binary offered over a network must provide
the corresponding source. Cloak's binary is proprietary; its wrapper is open,
but the patch source is not. The changes here are independent reimplementations
of observable behavior, not copied Cloak code.

## Reproduce

Built with Zig 0.17.0 and the prebuilt V8 15.5.35.13 archive. The resulting
binary is about 208 MB.

```bash
cd .plague/lightpanda-src
make download-v8

# Fetch the curl dependency, then apply the HTTP/2 patch
zig build --fetch
CURL_DIR=$(dirname "$(dirname "$(find zig-pkg -path '*/lib/http2.c' | head -1)")")
patch -p1 -d "$CURL_DIR" < ../../patches/curl-http2-chrome.patch

make build
./zig-out/bin/lightpanda serve --host 127.0.0.1 --port 9222
```

If `zig build --fetch` is not available, run `make build` once, apply the patch,
then run `make build` again.

Then point Plague at the patched binary:

```bash
export PLAGUE_LIGHTPANDA_BIN=$PWD/.plague/lightpanda-src/zig-out/bin/lightpanda
plague fingerprint --tier fast --json
```
