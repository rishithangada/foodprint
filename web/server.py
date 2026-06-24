#!/usr/bin/env python3
"""FoodPrint local dashboard server."""

from __future__ import annotations

import json
import mimetypes
import sqlite3
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


HOST = "localhost"
PORT = 9999
WEB_DIR = Path(__file__).resolve().parent
DB_PATH = WEB_DIR.parent / "logs" / "food_log.db"

FIELD_ALIASES = {
    "id": ("id", "entry_id"),
    "date": ("created_at", "timestamp", "logged_at", "date", "datetime", "time"),
    "food": ("food_name", "food", "name", "item"),
    "store": ("store", "store_name", "retailer"),
    "city": ("city", "location_city"),
    "state": ("state", "region"),
    "pesticide_score": ("pesticide_score", "pesticide", "pesticide_risk"),
    "microplastic_score": ("microplastic_score", "microplastic", "microplastic_risk"),
    "processing_score": ("processing_score", "processing", "processing_risk"),
    "overall_score": ("overall_score", "score", "overall", "concern_score"),
}


def _json_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _find_log_table(connection: sqlite3.Connection) -> tuple[str, list[str]] | None:
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    candidates = []
    for table in tables:
        quoted = table.replace('"', '""')
        columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{quoted}")')]
        lowered = {column.lower() for column in columns}
        confidence = sum(
            1 for key in ("food", "overall_score", "pesticide_score")
            if any(alias in lowered for alias in FIELD_ALIASES[key])
        )
        candidates.append((confidence, table, columns))
    if not candidates:
        return None
    _, table, columns = max(candidates, key=lambda item: item[0])
    return table, columns


def _column_map(columns: list[str]) -> dict[str, str | None]:
    actual = {column.lower(): column for column in columns}
    return {
        field: next((actual[alias] for alias in aliases if alias in actual), None)
        for field, aliases in FIELD_ALIASES.items()
    }


def read_entries(limit: int | None = 50) -> list[dict]:
    if not DB_PATH.is_file():
        return []

    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        discovered = _find_log_table(connection)
        if not discovered:
            return []
        table, columns = discovered
        mapping = _column_map(columns)
        order_column = mapping["date"] or mapping["id"] or "rowid"
        quoted_table = table.replace('"', '""')
        quoted_order = order_column.replace('"', '""')
        sql = f'SELECT * FROM "{quoted_table}" ORDER BY "{quoted_order}" DESC'
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        rows = connection.execute(sql, params).fetchall()

        entries = []
        for row in rows:
            entry = {}
            for field, column in mapping.items():
                value = row[column] if column else None
                entry[field] = _json_value(value)
            for score in ("pesticide_score", "microplastic_score", "processing_score", "overall_score"):
                try:
                    entry[score] = round(float(entry[score]), 1)
                except (TypeError, ValueError):
                    entry[score] = 0.0
            if not mapping["processing_score"]:
                # scorer.py weights overall as 45% pesticide, 35% microplastic,
                # and 20% processing. Older log schemas did not persist processing.
                inferred = (
                    entry["overall_score"]
                    - entry["pesticide_score"] * 0.45
                    - entry["microplastic_score"] * 0.35
                ) / 0.20
                entry["processing_score"] = round(max(0.0, min(10.0, inferred)), 1)
            entry["food"] = entry["food"] or "Unknown item"
            entry["store"] = entry["store"] or "Unknown"
            entry["city"] = entry["city"] or "—"
            entries.append(entry)
        return entries
    finally:
        connection.close()


def calculate_stats(entries: list[dict]) -> dict:
    count = len(entries)

    def average(field: str) -> float:
        return round(sum(entry[field] for entry in entries) / count, 1) if count else 0.0

    most_concerning = sorted(entries, key=lambda entry: entry["overall_score"], reverse=True)[:3]
    return {
        "avg_pesticide": average("pesticide_score"),
        "avg_microplastic": average("microplastic_score"),
        "avg_processing": average("processing_score"),
        "avg_overall": average("overall_score"),
        "total_entries": count,
        "most_concerning": [
            {"food": entry["food"], "score": entry["overall_score"]}
            for entry in most_concerning
        ],
    }


class FoodPrintHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

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
                self._send_json(read_entries(50))
                return
            if path == "/api/stats":
                self._send_json(calculate_stats(read_entries(None)))
                return
        except (sqlite3.Error, OSError) as exc:
            self._send_json({"error": "Unable to read the food log", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def end_headers(self) -> None:
        if self.path.endswith(".html"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    mimetypes.add_type("text/javascript", ".js")
    server = ThreadingHTTPServer((HOST, PORT), FoodPrintHandler)
    print(f"FoodPrint dashboard: http://{HOST}:{PORT}")
    print(f"Database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping FoodPrint.")
    finally:
        server.server_close()
