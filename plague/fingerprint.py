"""A cross-engine fingerprint probe used to measure stealth work."""

from __future__ import annotations

from typing import Any

FINGERPRINT_JS = r"""
() => {
  const safe = (fn, fallback = null) => {
    try { return fn(); } catch (e) { return "ERR:" + String(e).slice(0, 90); }
  };

  const canvas = document.createElement("canvas");
  canvas.width = 200;
  canvas.height = 50;
  const ctx = safe(() => canvas.getContext("2d"));
  let canvasPixel = null;
  let canvasData = null;
  if (ctx && ctx.fillRect) {
    safe(() => {
      ctx.textBaseline = "top";
      ctx.font = "14px Arial";
      ctx.fillStyle = "#ff6600";
      ctx.fillRect(0, 0, 200, 50);
      ctx.fillStyle = "#006699";
      ctx.fillText("plague", 2, 2);
    });
    canvasPixel = safe(() => Array.from(ctx.getImageData(0, 0, 1, 1).data));
    canvasData = safe(() => String(canvas.toDataURL()).slice(-72));
  }

  const gl = safe(() => canvas.getContext("webgl"));
  const readPlugins = safe(() => {
    const out = [];
    for (let i = 0; i < navigator.plugins.length; i++) {
      const plugin = navigator.plugins[i];
      out.push(plugin ? plugin.name : null);
    }
    return out;
  });
  const readMimes = safe(() => {
    const out = [];
    for (let i = 0; i < navigator.mimeTypes.length; i++) {
      const mime = navigator.mimeTypes[i];
      out.push(mime ? mime.type : null);
    }
    return out;
  });

  return {
    ua: navigator.userAgent,
    appVersion: navigator.appVersion,
    platform: navigator.platform,
    vendor: navigator.vendor,
    product: navigator.product,
    appName: navigator.appName,
    webdriver: navigator.webdriver,
    languages: navigator.languages,
    language: navigator.language,
    plugins: readPlugins,
    mimeTypes: readMimes,
    pdfViewerEnabled: navigator.pdfViewerEnabled,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: navigator.deviceMemory,
    chrome: typeof window.chrome,
    chromeKeys: typeof window.chrome === "object" ? Object.keys(window.chrome) : null,
    uaData: safe(() => navigator.userAgentData ? {
      brands: navigator.userAgentData.brands,
      mobile: navigator.userAgentData.mobile,
      platform: navigator.userAgentData.platform,
    } : null),
    screen: [screen.width, screen.height, screen.availWidth, screen.availHeight, screen.colorDepth, devicePixelRatio],
    window: [window.innerWidth, window.innerHeight, window.outerWidth, window.outerHeight],
    timezone: safe(() => Intl.DateTimeFormat().resolvedOptions().timeZone),
    canvas2d: ctx ? ctx.constructor.name : String(ctx),
    canvasPixel,
    canvasData,
    webgl: gl ? gl.constructor.name : String(gl),
    glVendor: gl ? safe(() => gl.getParameter(gl.VENDOR)) : null,
    glRenderer: gl ? safe(() => gl.getParameter(gl.RENDERER)) : null,
    audio: typeof AudioContext,
    rtc: typeof RTCPeerConnection,
    fonts: safe(() => document.fonts ? document.fonts.size : null),
    permissions: typeof navigator.permissions,
    notification: typeof Notification,
  };
}
"""


async def collect(session: Any) -> dict[str, Any]:
    """Run the probe on an already navigated Session."""
    result = await session.evaluate(FINGERPRINT_JS)
    return result if isinstance(result, dict) else {"error": str(result)}
