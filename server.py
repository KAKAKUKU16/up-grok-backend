"""
UP for Grok — High-Performance Lightweight API Server
Zero external dependencies. Handles Grok OpenAPI webhooks, pump.fun coin deployments,
and creator claim code verifications.
"""

import http.server
import json
import os
import sys

from pump_deployer import deploy_token, get_recent_launches
from claim_manager import verify_and_claim

PORT = int(os.environ.get("PORT", 8081))
BASE_DIR = os.path.dirname(__file__)

class UPHandler(http.server.BaseHTTPRequestHandler):
    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        url_path = self.path.split("?")[0]

        if url_path == "/api/health":
            self._send_json(200, {"status": "ok", "service": "UP for Grok", "network": "devnet"})
        elif url_path == "/api/coins":
            coins = get_recent_launches()
            self._send_json(200, coins)
        elif url_path in ["/openapi.json", "/api/openapi.json"]:
            spec_path = os.path.join(BASE_DIR, "openapi.json")
            if os.path.exists(spec_path):
                with open(spec_path, "r", encoding="utf-8") as f:
                    spec = json.load(f)
                self._send_json(200, spec)
            else:
                self._send_json(404, {"error": "openapi.json not found"})
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        url_path = self.path.split("?")[0]

        # Read JSON body
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            body = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            self._send_json(400, {"error": "Invalid JSON body"})
            return

        if url_path == "/api/launch":
            name = body.get("name", "").strip()
            symbol = body.get("symbol", "").strip()
            if not name or not symbol:
                self._send_json(400, {"error": "Both 'name' and 'symbol' are required (e.g. 'Test Cat', 'TCAT')."})
                return

            result = deploy_token(
                name=name,
                symbol=symbol,
                description=body.get("description", ""),
                image_url=body.get("image_url", "")
            )
            self._send_json(200, result)

        elif url_path == "/api/claim":
            claim_code = body.get("claimCode", "")
            wallet = body.get("walletAddress", "")
            if not claim_code or not wallet:
                self._send_json(400, {"error": "Both 'claimCode' and 'walletAddress' are required."})
                return

            result = verify_and_claim(claim_code, wallet)
            status_code = 200 if result.get("success") else 400
            self._send_json(status_code, result)

        else:
            self._send_json(404, {"error": "POST endpoint not found"})

    def _send_json(self, status: int, data: dict | list):
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self._send_cors()
        self.end_headers()
        self.wfile.write(payload)

def start_server():
    server_address = ("", PORT)
    httpd = http.server.ThreadingHTTPServer(server_address, UPHandler)
    print(f"🚀 UP for Grok API Server running at http://localhost:{PORT}")
    print(f"   • Health:    http://localhost:{PORT}/api/health")
    print(f"   • OpenAPI:   http://localhost:{PORT}/openapi.json")
    print(f"   • Deploy:    POST http://localhost:{PORT}/api/launch")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()

if __name__ == "__main__":
    start_server()
