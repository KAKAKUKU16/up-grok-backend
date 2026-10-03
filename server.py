"""
UP for Grok — High-Performance Lightweight API & MCP Server
Zero external dependencies.
Handles:
1. Grok Model Context Protocol (MCP) over SSE (/sse, /messages)
2. Grok OpenAPI webhooks (/api/launch, /api/claim, /api/coins, /openapi.json)
3. Creator bonus verification & pump.fun deployments
"""

import http.server
import json
import os
import queue
import secrets
import sys
import urllib.parse

from pump_deployer import deploy_token, get_recent_launches
from claim_manager import verify_and_claim

PORT = int(os.environ.get("PORT", 8081))
BASE_DIR = os.path.dirname(__file__)

# Global thread-safe sessions for MCP SSE streaming
mcp_sessions = {}

class UPHandler(http.server.BaseHTTPRequestHandler):
    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, Cache-Control")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        url_path = parsed_url.path

        if url_path in ["/sse", "/api/sse"]:
            self._handle_mcp_sse()
        elif url_path == "/api/health":
            self._send_json(200, {"status": "ok", "service": "UP for Grok", "network": "devnet", "mcp": True})
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

    def _handle_mcp_sse(self):
        session_id = secrets.token_hex(16)
        session_queue = queue.Queue()
        mcp_sessions[session_id] = session_queue

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._send_cors()
        self.end_headers()

        # Send initial endpoint event per MCP SSE specification
        endpoint_event = f"event: endpoint\r\ndata: /messages?sessionId={session_id}\r\n\r\n"
        self.wfile.write(endpoint_event.encode("utf-8"))
        self.wfile.flush()

        # Keep connection open and stream messages
        try:
            while True:
                try:
                    msg = session_queue.get(timeout=15.0)
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # Keep-alive ping
                    self.wfile.write(b": ping\r\n\r\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            mcp_sessions.pop(session_id, None)

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        url_path = parsed_url.path

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)

        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        # MCP JSON-RPC protocol endpoint
        if url_path in ["/messages", "/sse", "/api/messages", "/api/sse"]:
            self._handle_mcp_message(parsed_url, body)
            return

        # REST Endpoints
        if url_path == "/api/launch":
            name = body.get("name", "Unnamed Coin")
            symbol = body.get("symbol", "UP")
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

    def _handle_mcp_message(self, parsed_url, body: dict):
        query_params = urllib.parse.parse_qs(parsed_url.query)
        session_id = query_params.get("sessionId", [None])[0]

        method = body.get("method")
        req_id = body.get("id")
        resp = None

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "UP for Grok",
                        "version": "1.0.0"
                    }
                }
            }
        elif method in ["notifications/initialized", "initialized"]:
            self.send_response(202)
            self._send_cors()
            self.end_headers()
            return
        elif method == "ping":
            resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "launch_coin",
                            "description": "Deploy a new memecoin on pump.fun with Solana SPL bonding curve and creator reward claim code. Triggered when user asks to launch or upload a coin (e.g. 'UPload It. [NAME], [TICKER]').",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "The name of the coin (e.g. 'Test Cat')"
                                    },
                                    "symbol": {
                                        "type": "string",
                                        "description": "The token symbol/ticker (e.g. 'TCAT')"
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Optional short description for pump.fun"
                                    }
                                },
                                "required": ["name", "symbol"]
                            }
                        },
                        {
                            "name": "claim_bonus",
                            "description": "Verify and claim creator 3 SOL bonus and 20% rev-share for a bonded coin.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "claimCode": {
                                        "type": "string",
                                        "description": "The UP-XXXX-XXXX claim code"
                                    },
                                    "walletAddress": {
                                        "type": "string",
                                        "description": "Solana wallet address to receive the 3 SOL bonus"
                                    }
                                },
                                "required": ["claimCode", "walletAddress"]
                            }
                        }
                    ]
                }
            }
        elif method == "tools/call":
            params = body.get("params", {})
            tool_name = params.get("name")
            args = params.get("arguments", {})

            if tool_name == "launch_coin":
                name = args.get("name", "Test Coin")
                symbol = args.get("symbol", "TEST")
                desc = args.get("description", "Launched via UP for Grok")
                launch_res = deploy_token(name=name, symbol=symbol, description=desc)

                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"🚀 {launch_res['name']} (${launch_res['symbol']}) is LIVE on pump.fun!\n"
                                    f"• Contract Address: {launch_res['mint']}\n"
                                    f"• Live Trading: {launch_res['pumpUrl']}\n"
                                    f"• Creator Claim Code: {launch_res['claimCode']}\n\n"
                                    f"Bond ${launch_res['symbol']} on pump.fun to claim 3 SOL and 20% perpetual fee rev-share at https://hitup.fun with your claim code!"
                                )
                            }
                        ]
                    }
                }
            elif tool_name == "claim_bonus":
                code = args.get("claimCode", "")
                wallet = args.get("walletAddress", "")
                claim_res = verify_and_claim(code, wallet)

                msg = claim_res.get("message") if claim_res.get("success") else claim_res.get("error")
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"✅ Claim Result: {msg}"
                            }
                        ]
                    }
                }
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}
                }
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            }

        # Stream event over SSE if session exists
        if session_id and session_id in mcp_sessions and resp is not None:
            sse_data = f"event: message\r\ndata: {json.dumps(resp)}\r\n\r\n"
            try:
                mcp_sessions[session_id].put(sse_data)
            except Exception:
                pass

        # Return direct JSON-RPC HTTP response
        if resp is not None:
            self._send_json(200, resp)
        else:
            self.send_response(204)
            self._send_cors()
            self.end_headers()

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
    print(f"🚀 UP for Grok API & MCP Server running at http://localhost:{PORT}")
    print(f"   • MCP SSE:   http://localhost:{PORT}/sse")
    print(f"   • Health:    http://localhost:{PORT}/api/health")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()

if __name__ == "__main__":
    start_server()
