# Lightpanda Chrome persona patch

`lightpanda-chrome-persona.patch` is an independent reimplementation of the
fingerprint surfaces that can be ported to Lightpanda's architecture. It is not
copied CloakBrowser code.

Base commit:

```
c3b9247c4f979a75b61947925b8584b79bd25c1f
```

Apply to a fresh clone:

```bash
git clone https://github.com/lightpanda-io/browser
cd browser
git checkout c3b9247c4f979a75b61947925b8584b79bd25c1f
git apply /path/to/lightpanda-chrome-persona.patch

make download-v8
make build
```

The result is `zig-out/bin/lightpanda`. Point Plague at it:

```bash
export PLAGUE_LIGHTPANDA_BIN=$PWD/zig-out/bin/lightpanda
plague fingerprint --tier fast --json
```

## What the patch changes

- Chrome 146 Windows User-Agent by default
- Chrome brand list for `Sec-CH-UA` and `navigator.userAgentData`
- Allows `Mozilla/...` through the `--user-agent` validator and CDP override
- `navigator.platform` -> `Win32`
- `navigator.vendor` -> `Google Inc.`
- `navigator.appVersion` -> Chrome 146 Windows app version
- `hardwareConcurrency` -> 8
- `navigator.userAgentData.platform` -> `Windows`
- CDP `Emulation.setUserAgentOverride` no longer rejects Mozilla
- `Sec-Ch-Ua-Mobile` and `Sec-Ch-Ua-Platform` baseline headers
- Ignores an empty User-Agent override instead of blanking the UA
- Chrome TLS cipher list, curves, GREASE, OCSP stapling, SCT, extension
  permutation
- Built-in persona script before page scripts:
  - plugins and mimeTypes
  - `window.chrome`
  - screen and window dimensions
  - `navigator.connection`
  - `navigator.pdfViewerEnabled`

## Curl HTTP/2 patch

`curl-http2-chrome.patch` changes the bundled libcurl 8.23.0:

- HTTP/2 SETTINGS: `HEADER_TABLE_SIZE=65536`, `ENABLE_PUSH=0`,
  `INITIAL_WINDOW_SIZE=6291456`, `MAX_HEADER_LIST_SIZE=262144`
- Initial stream window 6 MiB
- Connection window 15 MiB
- Pseudo-header order `:method`, `:authority`, `:scheme`, `:path`

Apply it after the first dependency fetch:

```bash
cd .plague/lightpanda-src
zig build --fetch
CURL_DIR=$(dirname "$(dirname "$(find zig-pkg -path '*/lib/http2.c' | head -1)")")
patch -p1 -d "$CURL_DIR" < ../../patches/curl-http2-chrome.patch
make build
```

If `zig build --fetch` is not available in your Zig version, run `make build`
once, apply the patch, then run `make build` again.

## What it does not change

- Canvas 2D is still Lightpanda's stub. `getImageData` returns blank pixels.
- WebGL and WebGPU are still absent.
- WebRTC is still absent.
- Font metrics on canvas are still absent.
- TLS ClientHello and HTTP/2 settings are not yet matched to Chrome. The build
  uses BoringSSL and nghttp2, so this is possible, but it is a separate change.

## Verified

Against `https://tls.browserleaks.com/json`:

| Signal | Patched Lightpanda | CloakBrowser |
|---|---|---|
| JA4 | `t13d1512h2_8daaf6152771_ebb265cc0ce3` | `t13d1516h2_8daaf6152771_d8a2da3f94cd` |
| JA4 cipher hash | `8daaf6152771` | `8daaf6152771` |
| Akamai HTTP/2 hash | `52d84b11737d980aef856699f885ca86` | same |

The remaining JA4 difference is the four missing extensions listed above.

## Licensing

Lightpanda is AGPL-3.0. If you serve the modified binary over a network, you
must make the corresponding source available. See the upstream LICENSE.
