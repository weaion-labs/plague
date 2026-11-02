"""Local deterministic pages for speed and accuracy benchmarks."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


def clean_page(n: int) -> str:
    paragraphs = "\n".join(
        f"<p>token-{n}-{i} lorem ipsum dolor sit amet consectetur adipiscing.</p>"
        for i in range(30)
    )
    return f"""<!doctype html>
<html><head><title>Clean Page {n}</title></head>
<body>
  <h1>Alpha {n}</h1>
  {paragraphs}
  <a href="/clean/{n + 1}">next</a>
  <form><input name="q" value="test"></form>
</body></html>"""


def js_page(n: int) -> str:
    return f"""<!doctype html>
<html><head><title>JS Page {n}</title></head>
<body>
  <div id="root">loading</div>
  <script>
    setTimeout(function () {{
      document.getElementById("root").innerHTML =
        "<h1>Hydrated {n}</h1><p>js-token-{n}</p>";
    }}, 50);
  </script>
</body></html>"""


def large_page() -> str:
    paragraphs = "\n".join(
        f"<p>large-token-{i} " + "lorem ipsum dolor sit amet " * 6 + "</p>"
        for i in range(1200)
    )
    return f"""<!doctype html>
<html><head><title>Large Page</title></head>
<body><h1>Large</h1>{paragraphs}</body></html>"""


CF_HTML = """
<html><head><title>Just a moment...</title></head>
<body><script src="/cdn-cgi/challenge-platform/x.js"></script></body></html>
"""

RECAPTCHA_HTML = """
<html><body><div class="g-recaptcha" data-sitekey="SITE_KEY"></div>
<script src="https://www.google.com/recaptcha/api.js"></script></body></html>
"""

HCAPTCHA_HTML = """
<html><body><div class="h-captcha" data-sitekey="HCAP_KEY"></div></body></html>
"""

TURNSTILE_HTML = """
<html><body><div class="cf-turnstile" data-sitekey="TURN_KEY"></div></body></html>
"""

DATADOME_HTML = """
<html><body>captcha-delivery.com</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        status = 200
        headers: dict[str, str] = {}

        if path.startswith("/clean/"):
            n = int(path.rsplit("/", 1)[-1])
            body = clean_page(n)
        elif path.startswith("/js/"):
            n = int(path.rsplit("/", 1)[-1])
            body = js_page(n)
        elif path == "/large":
            body = large_page()
        elif path == "/redirect":
            status = 302
            headers["Location"] = "/clean/1"
            body = ""
        elif path == "/challenge/cloudflare":
            status = 403
            body = CF_HTML
            headers["cf-mitigated"] = "challenge"
        elif path == "/challenge/recaptcha":
            status = 403
            body = RECAPTCHA_HTML
        elif path == "/challenge/hcaptcha":
            status = 403
            body = HCAPTCHA_HTML
        elif path == "/challenge/turnstile":
            status = 403
            body = TURNSTILE_HTML
        elif path == "/challenge/datadome":
            status = 403
            body = DATADOME_HTML
            headers["set-cookie"] = "datadome=local; Path=/"
        else:
            status = 404
            body = "<html><body>not found</body></html>"

        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def log_message(self, *args) -> None:
        return None


def start_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


if __name__ == "__main__":
    server, base = start_server()
    print(base)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
