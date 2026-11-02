"""Offline accuracy test for the challenge detector.

No browser, no network. Each case has a known vendor and blocking state.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plague.challenge import detect  # noqa: E402

CLEAN = (
    "<html><head><title>Shop</title></head><body>"
    + "<p>product listing and documentation</p>" * 400
    + "</body></html>"
)

RECAPTCHA_WIDGET = (
    '<div class="g-recaptcha" data-sitekey="SITE_KEY"></div>'
    '<script src="https://www.google.com/recaptcha/api.js"></script>'
)


@dataclass(frozen=True)
class Case:
    name: str
    status: int
    html: str
    vendor: str | None
    blocking: bool
    solvable: bool = False
    headers: dict[str, str] | None = None


CASES = [
    Case("clean", 200, CLEAN, None, False),
    Case(
        "recaptcha_widget_nonblocking",
        200,
        CLEAN.replace("</body>", RECAPTCHA_WIDGET + "</body>"),
        "recaptcha",
        False,
    ),
    Case(
        "recaptcha_v2_blocking",
        403,
        "<html><body>" + RECAPTCHA_WIDGET + "</body></html>",
        "recaptcha",
        True,
        True,
    ),
    Case(
        "recaptcha_v3",
        200,
        '<html><body><script src="https://www.google.com/recaptcha/api.js?render=KEY">'
        "</script>" + "<p>real content</p>" * 300 + "</body></html>",
        "recaptcha_v3",
        False,
    ),
    Case(
        "hcaptcha_blocking",
        403,
        '<html><body><div class="h-captcha" data-sitekey="HCAP_KEY"></div></body></html>',
        "hcaptcha",
        True,
        True,
    ),
    Case(
        "hcaptcha_uuid_in_grecaptcha",
        403,
        '<html><body><div class="g-recaptcha" '
        'data-sitekey="58366d97-3e8c-4b57-a679-4a41c8423be3"></div></body></html>',
        "hcaptcha",
        True,
        True,
    ),
    Case(
        "turnstile_blocking",
        403,
        '<html><body><div class="cf-turnstile" data-sitekey="TURN_KEY"></div></body></html>',
        "cloudflare_turnstile",
        True,
        True,
    ),
    Case(
        "turnstile_nonblocking",
        200,
        CLEAN.replace(
            "</body>",
            '<div class="cf-turnstile" data-sitekey="TURN_KEY"></div></body>',
        ),
        "cloudflare_turnstile",
        False,
    ),
    Case(
        "cloudflare_header",
        200,
        "<html><body>ok</body></html>",
        "cloudflare",
        True,
        headers={"cf-mitigated": "challenge"},
    ),
    Case(
        "cloudflare_interstitial",
        403,
        '<html><head><title>Just a moment...</title></head><body>'
        '<script src="/cdn-cgi/challenge-platform/x.js"></script></body></html>',
        "cloudflare",
        True,
    ),
    Case(
        "datadome_blocking",
        403,
        "<html><body>captcha-delivery.com</body></html>",
        "datadome",
        True,
        headers={"set-cookie": "datadome=abc; Path=/"},
    ),
    Case(
        "datadome_clean",
        200,
        CLEAN.replace("</body>", "<script>datadome</script></body>"),
        "datadome",
        False,
    ),
    Case(
        "kasada_clean",
        200,
        CLEAN.replace("</body>", "<script>KPSDK</script></body>"),
        "kasada",
        False,
    ),
    Case(
        "akamai_clean",
        200,
        CLEAN.replace("</body>", "<script>_abck</script></body>"),
        "akamai",
        False,
    ),
    Case(
        "imperva_clean",
        200,
        CLEAN.replace("</body>", "<script>visid_incap</script></body>"),
        "imperva",
        False,
    ),
    Case(
        "aws_waf",
        403,
        '<html><body><script src="https://captcha.awswaf.com/x.js"></script></body></html>',
        "aws_waf",
        True,
    ),
    Case(
        "vercel_header",
        200,
        "<html><body>one moment</body></html>",
        "vercel",
        True,
        headers={"x-vercel-mitigated": "challenge"},
    ),
    Case(
        "generic_interstitial",
        403,
        "<html><body>Verify you are human</body></html>",
        "generic",
        True,
    ),
    Case(
        "large_docs_access_denied_clean",
        200,
        "<html><body>"
        + "<p>This article explains why access denied errors happen.</p>" * 2000
        + "</body></html>",
        None,
        False,
    ),
    Case(
        "http_403_no_signature",
        403,
        "<html><body>no</body></html>",
        "http",
        True,
    ),
]


def main() -> None:
    vendor_ok = 0
    blocking_ok = 0
    solvable_ok = 0
    tp = fp = tn = fn = 0
    failures: list[str] = []

    for case in CASES:
        challenge = detect(
            status=case.status,
            url="https://target.test/",
            headers=case.headers or {},
            html=case.html,
        )
        vendor = challenge.vendor if challenge else None
        blocking = bool(challenge.blocking) if challenge else False
        solvable = bool(challenge.solvable) if challenge else False

        vendor_match = vendor == case.vendor
        blocking_match = blocking == case.blocking
        solvable_match = solvable == case.solvable
        vendor_ok += vendor_match
        blocking_ok += blocking_match
        solvable_ok += solvable_match

        if case.blocking and blocking:
            tp += 1
        elif case.blocking and not blocking:
            fn += 1
        elif not case.blocking and blocking:
            fp += 1
        else:
            tn += 1

        if not (vendor_match and blocking_match and solvable_match):
            failures.append(
                f"{case.name:32} expected=({case.vendor},{case.blocking},{case.solvable}) "
                f"got=({vendor},{blocking},{solvable})"
            )

    total = len(CASES)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    print(f"cases: {total}")
    print(f"vendor accuracy:   {100 * vendor_ok / total:.1f}%")
    print(f"blocking accuracy: {100 * blocking_ok / total:.1f}%")
    print(f"solvable accuracy: {100 * solvable_ok / total:.1f}%")
    print(f"blocking precision: {100 * precision:.1f}%")
    print(f"blocking recall:    {100 * recall:.1f}%")
    if failures:
        print("\nmismatches:")
        for failure in failures:
            print(f"  {failure}")
    else:
        print("\nno mismatches")


if __name__ == "__main__":
    main()
