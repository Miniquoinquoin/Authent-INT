# syntax=docker/dockerfile:1
#
# STUB — à remplacer par les vrais Resource Servers (docs/architecture.md §3).
# Il existe uniquement pour que `docker compose up` démarre et que le routage
# Caddy + TLS soit vérifiable dès aujourd'hui. Répond 200 sur tout.
FROM python:3.13-alpine

ENV SERVICE_NAME=svc-impots \
    PORT=8001

COPY <<'PY' /app/stub.py
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

SERVICE = os.environ.get("SERVICE_NAME", "service")
PORT = int(os.environ.get("PORT", "8000"))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(
            {"service": SERVICE, "path": self.path, "stub": True}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{SERVICE} {fmt % args}", flush=True)


HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
PY

EXPOSE 8001
CMD ["python", "-u", "/app/stub.py"]
