"""IlaajSaathi HTTP server - Python standard library only.

Routes
  GET  /                 web app
  GET  /api/health       health check
  POST /api/chat         {message, session_id?, lat?, lng?, image_b64?, image_type?} -> full agent result
  POST /invoke           {input, session_id?} -> {output, ...}  (simple endpoint for API-based submission)
  GET  /files/<name>     generated PDF summaries and .ics reminders

Run:  python -m app.server     (PORT env var, default 8000)
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import agent, geo, llm, tools

STATIC = os.path.join(os.path.dirname(__file__), "static")
MAX_BODY = 8 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "IlaajSaathi/1.0"

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=list).encode(), "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("Request too large (max 8 MB)")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode() or "{}")

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._file(os.path.join(STATIC, "index.html"))
        if path == "/api/health":
            return self._json(200, {"status": "ok", "agent": "IlaajSaathi", "llm": llm.provider() or "rules",
                                     "maps": geo.maps_source()})
        if path.startswith("/static/"):
            name = os.path.basename(path)
            return self._file(os.path.join(STATIC, name))
        if path.startswith("/files/"):
            name = os.path.basename(path)
            if not re.fullmatch(r"(summary|reminder)-[0-9a-f]{8}\.(pdf|ics)", name):
                return self._json(404, {"error": "not found"})
            disp = {"Content-Disposition": f'attachment; filename="{name}"'} if name.endswith(".ics") else None
            return self._file(os.path.join(tools.OUT_DIR, name), disp)
        self._json(404, {"error": "not found"})

    def _file(self, fp: str, extra: dict | None = None):
        if not os.path.isfile(fp):
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        if fp.endswith(".ics"):
            ctype = "text/calendar"
        with open(fp, "rb") as f:
            self._send(200, f.read(), ctype, extra)

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            data = self._body()
        except Exception as e:
            return self._json(400, {"error": f"Bad request: {e}"})
        if path in ("/api/chat", "/invoke", "/api/invoke"):
            msg = (data.get("message") or data.get("input") or data.get("query") or "").strip()
            if not msg and not data.get("image_b64"):
                return self._json(400, {"error": "Send a 'message' describing the health problem."})
            try:
                loc = data.get("location") or {}
                lat = data.get("lat", loc.get("lat"))
                lng = data.get("lng", loc.get("lng"))
                res = agent.handle(msg or "Please read my prescription.", data.get("session_id"),
                                   data.get("image_b64"), data.get("image_type") or "image/jpeg",
                                   float(lat) if lat is not None else None, float(lng) if lng is not None else None)
            except Exception as e:
                return self._json(500, {"error": f"Agent error: {e}"})
            if path != "/api/chat":
                res = {"output": res["reply"], **res}
            return self._json(200, res)
        self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        print("[http]", self.address_string(), fmt % args)


def main():
    port = int(os.environ.get("PORT", "8000"))
    print(f"IlaajSaathi running on http://0.0.0.0:{port}  (llm: {llm.provider() or 'rules'}, maps: {geo.maps_source()})")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
