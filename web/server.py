#!/usr/bin/env python3
"""FoodPrint local dashboard server."""

from __future__ import annotations

import json
import sys
import mimetypes
import sqlite3
from dataclasses import asdict
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.scorer import score_food
from engine.origin import detect_origin
from engine.database import save_entry, init_db, get_history, get_stats

HOST = "localhost"
PORT = 9999
WEB_DIR = Path(__file__).resolve().parent

PACKAGING_OPTIONS = [
    "plastic wrap", "plastic clamshell", "plastic bag", "plastic bottle",
    "plastic tray", "styrofoam", "can", "tetra pak", "cardboard",
    "glass", "paper bag", "none", "unknown",
]


def _read_body(handler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length)
    return json.loads(raw)


def api_scan(payload: dict) -> dict:
    food_name  = str(payload.get("food_name", "")).strip()
    store      = str(payload.get("store", "")).strip()
    city       = str(payload.get("city", "")).strip()
    state      = str(payload.get("state", "")).strip()
    country    = str(payload.get("country", "USA")).strip() or "USA"
    packaging  = str(payload.get("packaging", "unknown")).strip()
    organic    = bool(payload.get("organic", False))

    if not food_name:
        raise ValueError("food_name is required")

    scored  = score_food(food_name, store, city, state, country, packaging, organic)
    origins = detect_origin(food_name, store, city=city, state=state)
    result  = asdict(scored)
    result["origins"] = origins

    origin_primary = origins[0][0] if origins else "Unknown"
    save_entry({**result, "origin_primary": origin_primary})

    return result


def api_history() -> list:
    rows = get_history(50)
    out = []
    for r in rows:
        out.append({
            "id":               r.get("id"),
            "date":             r.get("logged_at", ""),
            "food":             r.get("food_name", ""),
            "store":            r.get("store", ""),
            "city":             r.get("city", ""),
            "state":            r.get("state", ""),
            "pesticide_score":  round(float(r.get("pesticide_score") or 0), 1),
            "microplastic_score": round(float(r.get("microplastic_score") or 0), 1),
            "processing_score": round(float(r.get("processing_score") or 0), 1),
            "overall_score":    round(float(r.get("overall_score") or 0), 1),
        })
    return out


def api_stats_out() -> dict:
    s = get_stats()
    return {
        "avg_pesticide":   round(float(s.get("avg_pesticide_score") or 0), 1),
        "avg_microplastic": round(float(s.get("avg_microplastic_score") or 0), 1),
        "avg_processing":  round(float(s.get("avg_processing_score") or 0), 1),
        "avg_overall":     round(float(s.get("avg_overall_score") or 0), 1),
        "total_entries":   s.get("total_entries", 0),
        "most_concerning": s.get("most_concerning", []),
    }


class FoodPrintHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/history":
                self._send_json(api_history())
                return
            if path == "/api/stats":
                self._send_json(api_stats_out())
                return
            if path == "/api/packaging-options":
                self._send_json(PACKAGING_OPTIONS)
                return
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/":
            self.path = "/index.html"
        elif path == "/news":
            self.path = "/news.html"
        elif path == "/tips":
            self.path = "/tips.html"
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/scan":
                payload = _read_body(self)
                result  = api_scan(payload)
                self._send_json(result)
                return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        if self.path.endswith(".html"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    mimetypes.add_type("text/javascript", ".js")
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), FoodPrintHandler)
    print(f"FoodPrint dashboard → http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
