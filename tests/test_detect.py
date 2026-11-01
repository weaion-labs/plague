from plague.challenge.detect import detect, find_sitekey
from plague.models import ChallengeKind

CLEAN_HTML = (
    "<html><head><title>Shop</title></head><body>"
    + "<p>product listing</p>" * 400
    + "</body></html>"
)

CF_HTML = """
<html><head><title>Just a moment...</title></head>
<body><div id="cf-chl-widget"></div>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>
</body></html>
"""

RECAPTCHA_HTML = """
<html><body>
<form><div class="g-recaptcha" data-sitekey="SITE_KEY_123"></div></form>
<script src="https://www.google.com/recaptcha/api.js"></script>
</body></html>
"""


def test_clean_page_is_clean():
    assert detect(status=200, url="https://shop.test/", headers={}, html=CLEAN_HTML) is None


def test_embedded_recaptcha_on_a_large_page_is_not_blocking():
    html = CLEAN_HTML.replace("</body>", RECAPTCHA_HTML + "</body>")
    challenge = detect(status=200, url="https://shop.test/", headers={}, html=html)
    assert challenge is not None
    assert challenge.vendor == "recaptcha"
    assert challenge.blocking is False
    assert challenge.solvable is False
    assert challenge.sitekey == "SITE_KEY_123"


def test_cloudflare_interstitial_is_blocking():
    challenge = detect(
        status=403,
        url="https://blocked.test/",
        headers={"cf-mitigated": "challenge"},
        html=CF_HTML,
    )
    assert challenge is not None
    assert challenge.vendor == "cloudflare"
    assert challenge.kind is ChallengeKind.JS
    assert challenge.blocking is True
    assert challenge.solvable is False


def test_cloudflare_header_alone_is_blocking():
    challenge = detect(
        status=200,
        url="https://blocked.test/",
        headers={"cf-mitigated": "challenge"},
        html="<html><body>ok</body></html>",
    )
    assert challenge is not None
    assert challenge.vendor == "cloudflare"
    assert challenge.blocking is True


def test_datadome_403_is_a_risk_wall():
    challenge = detect(
        status=403,
        url="https://blocked.test/",
        headers={"set-cookie": "datadome=abc; Path=/"},
        html="<html><body>captcha-delivery.com</body></html>",
    )
    assert challenge is not None
    assert challenge.vendor == "datadome"
    assert challenge.kind is ChallengeKind.RISK
    assert challenge.blocking is True
    assert challenge.solvable is False


def test_recaptcha_v2_interstitial_is_solvable():
    challenge = detect(
        status=403,
        url="https://blocked.test/",
        headers={},
        html=RECAPTCHA_HTML,
    )
    assert challenge is not None
    assert challenge.vendor == "recaptcha"
    assert challenge.kind is ChallengeKind.TOKEN
    assert challenge.blocking is True
    assert challenge.solvable is True
    assert challenge.sitekey == "SITE_KEY_123"


def test_recaptcha_v3_is_scored_not_solved():
    html = (
        '<html><body><script src="https://www.google.com/recaptcha/api.js?render=KEY">'
        "</script>" + "<p>real content</p>" * 300 + "</body></html>"
    )
    challenge = detect(status=200, url="https://shop.test/", headers={}, html=html)
    assert challenge is not None
    assert challenge.vendor == "recaptcha_v3"
    assert challenge.kind is ChallengeKind.RISK
    assert challenge.blocking is False
    assert challenge.solvable is False


def test_hcaptcha_sitekey_and_solvable():
    html = '<html><body><div class="h-captcha" data-sitekey="HCAP_KEY"></div></body></html>'
    challenge = detect(
        status=403, url="https://blocked.test/", headers={}, html=html
    )
    assert challenge is not None
    assert challenge.vendor == "hcaptcha"
    assert challenge.solvable is True
    assert challenge.sitekey == "HCAP_KEY"


def test_turnstile_sitekey_and_solvable():
    html = (
        '<html><body><div class="cf-turnstile" data-sitekey="TURN_KEY"></div>'
        "</body></html>"
    )
    challenge = detect(
        status=403, url="https://blocked.test/", headers={}, html=html
    )
    assert challenge is not None
    assert challenge.vendor == "cloudflare_turnstile"
    assert challenge.kind is ChallengeKind.TOKEN
    assert challenge.solvable is True
    assert challenge.sitekey == "TURN_KEY"


def test_large_403_without_signature_is_not_treated_as_a_wall():
    html = "<html><body>" + "<p>real content</p>" * 9000 + "</body></html>"
    assert detect(status=403, url="https://odd.test/", headers={}, html=html) is None


def test_large_page_mentioning_access_denied_is_not_a_wall():
    html = (
        "<html><body>"
        + "<p>This article explains why access denied errors happen.</p>" * 2000
        + "</body></html>"
    )
    challenge = detect(status=200, url="https://docs.test/", headers={}, html=html)
    assert challenge is None or challenge.blocking is False


def test_small_403_without_signature_is_a_generic_wall():
    challenge = detect(
        status=503, url="https://odd.test/", headers={}, html="<html><body>no</body></html>"
    )
    assert challenge is not None
    assert challenge.vendor == "http"
    assert challenge.blocking is True


def test_vercel_mitigation_header():
    challenge = detect(
        status=200,
        url="https://odd.test/",
        headers={"x-vercel-mitigated": "challenge"},
        html="<html><body>one moment</body></html>",
    )
    assert challenge is not None
    assert challenge.vendor == "vercel"
    assert challenge.blocking is True


def test_find_sitekey_from_iframe():
    html = '<iframe src="https://www.google.com/recaptcha/api2/anchor?k=ABC-123&hl=en"></iframe>'
    assert find_sitekey(html, "recaptcha") == "ABC-123"


def test_find_sitekey_returns_none_when_absent():
    assert find_sitekey("<html><body>nothing</body></html>", "hcaptcha") is None
