#!/usr/bin/env python3
"""
server.py  –  Servidor local per a Concerts Calendar
Ús: python server.py [port]   (per defecte port 8000)
Obre http://localhost:8000 al navegador.
"""
import json
import os
import sys
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
ARTISTS_FILE  = os.path.join(BASE_DIR, "artists.json")
CONCERTS_FILE = os.path.join(BASE_DIR, "concerts.json")

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Madrid")
except Exception:
    _TZ = None


def now_local():
    if _TZ:
        return datetime.now(_TZ).strftime("%Y-%m-%dT%H:%M:%S%z")
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def sync_concerts():
    """Elimina concerts d'artistes que ja no són a artists.json i actualitza last_updated."""
    with open(ARTISTS_FILE, "r", encoding="utf-8") as f:
        artists_data = json.load(f)
    known = {a["name"] for a in artists_data["artists"]}

    with open(CONCERTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    before = len(data.get("concerts", []))
    data["concerts"] = [c for c in data.get("concerts", []) if c.get("artist") in known]
    removed = before - len(data["concerts"])

    ts = now_local()
    data["last_updated"] = ts

    with open(CONCERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return {"ok": True, "total": len(data["concerts"]), "removed": removed, "last_updated": ts}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path.split("?")[0] == "/api/update":
            try:
                result = sync_concerts()
                self._json(200, result)
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
        else:
            self.send_error(404)

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def log_message(self, fmt, *args):
        sys.stdout.write(f"  {self.address_string()} – {fmt % args}\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    httpd = HTTPServer(("", port), Handler)
    print(f"Concerts Calendar  ->  http://localhost:{port}")
    print("Ctrl+C per aturar\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor aturat.")
