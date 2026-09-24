"""Tiny HTTP service: GET / -> {region, node, pod}. Env: REGION (from downward API), PORT."""
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer

REGION = os.environ.get("REGION", "unknown")
NODE = os.environ.get("NODE_NAME", socket.gethostname())


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"region": REGION, "node": NODE, "pod": socket.gethostname()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


HTTPServer(("", int(os.environ.get("PORT", "8080"))), H).serve_forever()
