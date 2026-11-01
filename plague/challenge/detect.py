"""Challenge and anti-bot wall detection.

Detection is deliberately conservative: a reCAPTCHA widget on a contact form
is not a block. Escalation only happens when the page itself looks like an
interstitial, the response status is hostile, or the vendor sets an explicit
mitigation header.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Mapping

from ..models import Challenge, ChallengeKind

BLOCK_STATUSES = {401, 403, 407, 429, 503}
HARD_HEADERS = {"cf-mitigated", "x-vercel-mitigated"}
MAX_SCAN = 500_000

INTERSTITIAL_PHRASES = (
    r"just a moment",
    r"attention required",
    r"checking your browser",
    r"verify (that )?you are (a )?human",
    r"are you a robot",
    r"enable javascript and cookies to continue",
    r"unusual traffic from your computer",
    r"please complete the security check",
    r"access to this page has been denied",
    r"request unsuccessful",
    r"you have been blocked",
    r"ddos protection by",
)


@dataclass(frozen=True)
class Signature:
    vendor: str
    kind: ChallengeKind
    weight: int
    solvable: bool
    patterns: tuple[str, ...] = ()
    headers: tuple[tuple[str, str], ...] = ()
    interstitial: bool = False


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        vendor="cloudflare",
        kind=ChallengeKind.JS,
        weight=96,
        solvable=False,
        patterns=(
            r"__cf_chl",
            r"cf_chl_opt",
            r"cf_chl_prog",
            r"cdn-cgi/challenge-platform",
            r"just a moment",
            r"attention required!?\s*\|\s*cloudflare",
            r"checking your browser before accessing",
        ),
        headers=(("cf-mitigated", r"challenge"),),
        interstitial=True,
    ),
    Signature(
        vendor="cloudflare_turnstile",
        kind=ChallengeKind.TOKEN,
        weight=82,
        solvable=True,
        patterns=(
            r"cf-turnstile",
            r"challenges\.cloudflare\.com/turnstile",
            r"turnstile\.render",
        ),
    ),
    Signature(
        vendor="recaptcha",
        kind=ChallengeKind.TOKEN,
        weight=64,
        solvable=True,
        patterns=(
            r"g-recaptcha",
            r"grecaptcha",
            r"recaptcha/(api|enterprise)\.js",
            r"www\.google\.com/recaptcha",
        ),
    ),
    Signature(
        vendor="hcaptcha",
        kind=ChallengeKind.TOKEN,
        weight=64,
        solvable=True,
        patterns=(
            r"h-captcha",
            r"hcaptcha\.com",
            r"new hcaptcha",
        ),
    ),
    Signature(
        vendor="datadome",
        kind=ChallengeKind.RISK,
        weight=92,
        solvable=False,
        patterns=(
            r"captcha-delivery\.com",
            r"geo\.captcha-delivery\.com",
            r"datadome",
        ),
        headers=(("x-datadome", r"."), ("set-cookie", r"datadome=")),
    ),
    Signature(
        vendor="perimeterx",
        kind=ChallengeKind.RISK,
        weight=92,
        solvable=False,
        patterns=(
            r"px-captcha",
            r"perimeterx",
            r"human-challenge",
            r"_pxAppId",
        ),
        headers=(("set-cookie", r"_px"),),
    ),
    Signature(
        vendor="kasada",
        kind=ChallengeKind.RISK,
        weight=92,
        solvable=False,
        patterns=(
            r"kpsdk",
            r"kasada",
            r"x-kpsdk",
        ),
        headers=(("x-kpsdk", r"."),),
    ),
    Signature(
        vendor="akamai",
        kind=ChallengeKind.RISK,
        weight=88,
        solvable=False,
        patterns=(
            r"_abck",
            r"bm_sz",
            r"akamai bot manager",
            r"reference #18",
            r"errors\.edgesuite\.net",
        ),
    ),
    Signature(
        vendor="imperva",
        kind=ChallengeKind.RISK,
        weight=88,
        solvable=False,
        patterns=(
            r"incapsula",
            r"visid_incap",
            r"_incapsula_resource",
        ),
    ),
    Signature(
        vendor="aws_waf",
        kind=ChallengeKind.TOKEN,
        weight=84,
        solvable=False,  # needs more than a sitekey; not supported in v1
        patterns=(
            r"awswaf",
            r"captcha\.awswaf\.com",
            r"gokuprops",
        ),
    ),
    Signature(
        vendor="vercel",
        kind=ChallengeKind.JS,
        weight=86,
        solvable=False,
        patterns=(r"vercel-challenge", r"_vcrcs"),
        headers=(("x-vercel-mitigated", r"challenge"),),
    ),
    Signature(
        vendor="generic",
        kind=ChallengeKind.UNKNOWN,
        weight=50,
        solvable=False,
        patterns=INTERSTITIAL_PHRASES,
        interstitial=True,
    ),
)

_RECAPTCHA_V3 = re.compile(
    r"recaptcha/(?:api|enterprise)\.js\?[^\"']*\brender=([\w-]+)", re.I
)
_RECAPTCHA_WIDGET = re.compile(r"g-recaptcha", re.I)


def _scan_text(html: str) -> str:
    return html[:MAX_SCAN]


def _header_value(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name:
            return str(value)
    return ""


def _has_interstitial_phrase(text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in INTERSTITIAL_PHRASES)


def _is_recaptcha_v3(html: str) -> bool:
    return bool(_RECAPTCHA_V3.search(html)) and not bool(_RECAPTCHA_WIDGET.search(html))


def _blocking(
    signature: Signature,
    *,
    status: int | None,
    url: str,
    text: str,
    hard_header_hit: bool,
) -> bool:
    if hard_header_hit:
        return True
    if status in BLOCK_STATUSES:
        return True
    if signature.vendor == "generic":
        # A large documentation page can mention "access denied" without being
        # a wall. Only trust the phrase on a small interstitial document.
        return _has_interstitial_phrase(text) and len(text) < 60_000
    if signature.interstitial and _has_interstitial_phrase(text):
        return True
    if signature.kind is ChallengeKind.RISK:
        if re.search(r"/(captcha|challenge|blocked|denied)\b", url, re.I):
            return True
        return _has_interstitial_phrase(text)
    return False


def detect(
    *,
    status: int | None,
    url: str,
    headers: Mapping[str, str] | None = None,
    html: str = "",
) -> Challenge | None:
    """Return the most relevant challenge, or None for a clean page."""
    headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    text = _scan_text(html)
    candidates: list[Challenge] = []

    for signature in SIGNATURES:
        evidence: list[str] = []
        header_hit = False
        hard_header_hit = False
        for name, pattern in signature.headers:
            value = _header_value(headers, name)
            if value and re.search(pattern, value, re.I):
                header_hit = True
                if name.lower() in HARD_HEADERS:
                    hard_header_hit = True
                evidence.append(f"header:{name}={value[:60]}")
        for pattern in signature.patterns:
            match = re.search(pattern, text, re.I) or re.search(pattern, url, re.I)
            if match:
                evidence.append(f"match:{match.group(0)[:60]}")
                if len(evidence) >= 3:
                    break
        if not evidence:
            continue

        kind = signature.kind
        solvable = signature.solvable
        vendor = signature.vendor

        if signature.vendor == "recaptcha" and _is_recaptcha_v3(text):
            vendor = "recaptcha_v3"
            kind = ChallengeKind.RISK
            solvable = False

        blocking = _blocking(
            signature,
            status=status,
            url=url,
            text=text,
            hard_header_hit=hard_header_hit,
        )
        candidates.append(
            Challenge(
                vendor=vendor,
                kind=kind,
                blocking=blocking,
                confidence=min(0.99, signature.weight / 100),
                evidence=tuple(evidence),
                solvable=solvable and blocking and kind is ChallengeKind.TOKEN,
            )
        )

    if not candidates:
        # A stale 403 from the challenge response can survive a DOM swap. Only
        # treat the status alone as a wall when the body is not a real page.
        if status in BLOCK_STATUSES and len(text) < 100_000:
            return Challenge(
                vendor="http",
                kind=ChallengeKind.UNKNOWN,
                blocking=True,
                confidence=0.5,
                evidence=(f"status:{status}",),
            )
        return None

    blocking_candidates = [c for c in candidates if c.blocking]
    if blocking_candidates:
        primary = max(blocking_candidates, key=lambda c: c.confidence)
    else:
        primary = max(candidates, key=lambda c: c.confidence)

    sitekey = find_sitekey(text, primary.vendor)
    if sitekey:
        primary = replace(primary, sitekey=sitekey)

    return primary


def find_sitekey(html: str, vendor: str) -> str | None:
    """Best-effort sitekey extraction for the token-based vendors."""
    text = _scan_text(html)
    if vendor in {"cloudflare_turnstile", "hcaptcha", "recaptcha"}:
        patterns = (
            r"data-sitekey=[\"']([^\"']+)[\"']",
            r"[\"']?sitekey[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']",
        )
        if vendor == "cloudflare_turnstile":
            patterns += (
                r"challenges\.cloudflare\.com/turnstile/[^\"']*\bk=([\w-]+)",
                r"turnstile[^\"']*\bsitekey=[\"']?([\w-]+)",
            )
        if vendor == "hcaptcha":
            patterns += (r"hcaptcha\.com/1/api\.js[^\"']*\bsitekey=([\w-]+)",)
        if vendor == "recaptcha":
            patterns += (
                r"recaptcha/(?:api|enterprise)\.js\?[^\"']*\brender=([\w-]+)",
                r"www\.google\.com/recaptcha/[^\"']*\bk=([\w-]+)",
            )
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(1)
    return None
