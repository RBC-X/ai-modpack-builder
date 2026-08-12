"""Local HTTPS mirror of the AI Modpack Builder update feed.

Serves the project root over TLS on https://127.0.0.1:8543 so the installed
launcher can check for updates with NO insecure dev flag (AMB_UPDATE_ALLOW_INSECURE
is not needed — the certificate below is trusted in the machine Root store).

Endpoints:
  /workspace/update-feed-https/update.json   the feed
  /installers/AI-Modpack-Builder-Setup-*.exe the installers

Run (persistent):  powershell Start-Process -WindowStyle Hidden \
                     "<venv>\\pythonw.exe" pyqt\\serve_feed_https.py
"""

from __future__ import annotations

import http.server
import os
import ssl
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # pyqt/
ROOT = HERE.parent                              # project root (served)
CERT = ROOT / "workspace" / "feed-tls" / "cert.pem"
KEY = ROOT / "workspace" / "feed-tls" / "key.pem"
HOST, PORT = "127.0.0.1", int(os.environ.get("AMB_FEED_PORT", "8543"))


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: N802  (keep the mirror silent)
        # pythonw has no stderr (None) — never let logging kill a handler
        # thread, or the client sees "remote closed connection without response".
        try:
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    if not CERT.exists() or not KEY.exists():
        print("missing TLS key/cert — run the feed-tls generation first", file=sys.stderr)
        return 1
    httpd = http.server.ThreadingHTTPServer((HOST, PORT), QuietHandler)
    httpd.directory = str(ROOT)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(CERT), str(KEY))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print(f"HTTPS update-feed mirror on https://{HOST}:{PORT}", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
