#!/usr/bin/env python3
"""FoodPrint local dashboard server."""

from __future__ import annotations

import json
import os
import sys
import mimetypes
import sqlite3
import urllib.request
import urllib.error
from dataclasses import asdict
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from engine.scorer import score_food
from engine.origin import detect_origin
from engine.database import save_entry, init_db, get_history, get_stats

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.1-8b-instruct:free"


def _llm_enrich(result: dict, inputs: dict) -> dict:
    """Call OpenRouter to generate specific verdict + details. Falls back silently."""
    if not OPENROUTER_KEY:
        return result

    food     = inputs["food_name"]
    store    = inputs["store"] or "an unspecified store"
    city     = inputs["city"] or "unknown city"
    state    = inputs["state"] or "unknown state"
    pkg      = inputs["packaging"]
    organic  = "organic" if inputs["organic"] else "conventional"

    prompt = f"""You are a food contamination analyst. Be direct, specific, and practical.

Food scanned: {food} ({organic})
Purchased at: {store}, {city}, {state}
Packaging: {pkg}
Scores (0-10, higher = worse):
  Pesticide residue: {result['pesticide_score']} ({result['pesticide_label']})
  Microplastic exposure: {result['microplastic_score']} ({result['microplastic_label']})
  Processing level: {result['processing_score']} ({result['processing_label']})
  Overall concern: {result['overall_score']} ({result['overall_label']})

Write exactly 3 outputs, each on its own line, prefixed as shown:
VERDICT: [2-3 sentences. Specific to this exact food, store, city, and packaging. Actionable. No generic advice.]
PESTICIDE: [1-2 sentences specific to {food} pesticide reality and what {store} customers should know.]
PACKAGING: [1-2 sentences specific to {food} in {pkg} — what exactly is the risk and what to do.]

Be blunt. Reference the specific store, city, and food by name."""

    payload = json.dumps({
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 320,
        "temperature": 0.4,
    }).encode()

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:9999",
            "X-Title": "FoodOverkill",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"].strip()

        for line in text.splitlines():
            line = line.strip()
            if line.startswith("VERDICT:"):
                result["verdict"] = line[8:].strip()
            elif line.startswith("PESTICIDE:"):
                result["pesticide_detail"] = line[10:].strip()
            elif line.startswith("PACKAGING:"):
                result["microplastic_detail"] = line[10:].strip()

    except Exception as e:
        print(f"[OpenRouter] fallback to hardcoded: {e}")

    return result

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

    # Enrich with LLM if OpenRouter key is available
    result = _llm_enrich(result, {
        "food_name": food_name, "store": store, "city": city,
        "state": state, "packaging": packaging, "organic": organic,
    })

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
