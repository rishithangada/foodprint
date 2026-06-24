"""
SQLite persistence for FoodPrint.

Stores each logged food and exposes history + aggregate stats. The DB lives at
~/foodprint/logs/food_log.db and is created on first use.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path.home() / "foodprint" / "logs" / "food_log.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS food_entries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    food_name        TEXT    NOT NULL,
    store            TEXT,
    city             TEXT,
    state            TEXT,
    country          TEXT,
    packaging        TEXT,
    organic          INTEGER,          -- 0 / 1
    pesticide_score  REAL,
    microplastic_score REAL,
    processing_score REAL,
    overall_score    REAL,
    verdict          TEXT,
    origin_primary   TEXT,
    logged_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns we accept from a caller's data dict (logged_at is auto unless given).
_FIELDS = [
    "food_name", "store", "city", "state", "country", "packaging",
    "organic", "pesticide_score", "microplastic_score", "processing_score",
    "overall_score", "verdict", "origin_primary", "logged_at",
]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the table if it does not exist. Safe to call repeatedly."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(food_entries)")}
        if "processing_score" not in columns:
            try:
                conn.execute("ALTER TABLE food_entries ADD COLUMN processing_score REAL")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise


def save_entry(data: dict[str, Any]) -> int:
    """
    Insert one food entry. Accepts any subset of the known fields; unknown
    keys are ignored, missing keys store NULL. `organic` may be passed as a
    bool. Returns the new row id.
    """
    init_db()

    row = {}
    for key in _FIELDS:
        if key not in data:
            continue
        value = data[key]
        if key == "organic" and value is not None:
            value = 1 if value else 0
        row[key] = value

    if "food_name" not in row or not row["food_name"]:
        raise ValueError("save_entry requires a 'food_name'")

    cols = ", ".join(row)
    placeholders = ", ".join(f":{c}" for c in row)
    sql = f"INSERT INTO food_entries ({cols}) VALUES ({placeholders})"

    with _connect() as conn:
        cur = conn.execute(sql, row)
        conn.commit()
        return cur.lastrowid


def get_history(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent entries, newest first, as plain dicts."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM food_entries ORDER BY logged_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict[str, Any]:
    """
    Aggregate summary:

        {
          "total_entries": int,
          "avg_pesticide_score": float | None,
          "avg_microplastic_score": float | None,
          "avg_overall_score": float | None,
          "organic_pct": float | None,
          "most_logged": [ {food_name, count}, ... ],      # top 5
          "most_concerning": [ {food_name, avg_overall_score}, ... ],  # top 5
          "top_store": {store, count} | None,
        }

    'most_concerning' assumes a higher overall_score is worse.
    """
    init_db()
    with _connect() as conn:
        agg = conn.execute(
            """
            SELECT
                COUNT(*)                       AS total_entries,
                AVG(pesticide_score)           AS avg_pesticide_score,
                AVG(microplastic_score)        AS avg_microplastic_score,
                AVG(processing_score)          AS avg_processing_score,
                AVG(overall_score)             AS avg_overall_score,
                AVG(CASE WHEN organic IS NOT NULL THEN organic END) AS organic_frac
            FROM food_entries
            """
        ).fetchone()

        most_logged = conn.execute(
            """
            SELECT food_name, COUNT(*) AS count
            FROM food_entries
            GROUP BY LOWER(food_name)
            ORDER BY count DESC, food_name ASC
            LIMIT 5
            """
        ).fetchall()

        most_concerning = conn.execute(
            """
            SELECT food_name, AVG(overall_score) AS avg_overall_score
            FROM food_entries
            WHERE overall_score IS NOT NULL
            GROUP BY LOWER(food_name)
            ORDER BY avg_overall_score DESC, food_name ASC
            LIMIT 5
            """
        ).fetchall()

        top_store = conn.execute(
            """
            SELECT store, COUNT(*) AS count
            FROM food_entries
            WHERE store IS NOT NULL AND store != ''
            GROUP BY LOWER(store)
            ORDER BY count DESC, store ASC
            LIMIT 1
            """
        ).fetchone()

    def _round(v: Optional[float]) -> Optional[float]:
        return round(v, 2) if v is not None else None

    organic_frac = agg["organic_frac"]
    return {
        "total_entries": agg["total_entries"] or 0,
        "avg_pesticide_score": _round(agg["avg_pesticide_score"]),
        "avg_microplastic_score": _round(agg["avg_microplastic_score"]),
        "avg_processing_score": _round(agg["avg_processing_score"]),
        "avg_overall_score": _round(agg["avg_overall_score"]),
        "organic_pct": _round(organic_frac * 100) if organic_frac is not None else None,
        "most_logged": [dict(r) for r in most_logged],
        "most_concerning": [
            {"food_name": r["food_name"], "avg_overall_score": _round(r["avg_overall_score"])}
            for r in most_concerning
        ],
        "top_store": dict(top_store) if top_store else None,
    }


if __name__ == "__main__":
    init_db()
    save_entry({
        "food_name": "Strawberries",
        "store": "Whole Foods",
        "city": "Austin",
        "state": "Texas",
        "country": "Mexico",
        "packaging": "plastic clamshell",
        "organic": True,
        "pesticide_score": 6.5,
        "microplastic_score": 4.0,
        "overall_score": 5.2,
        "verdict": "moderate",
        "origin_primary": "Mexico",
    })
    print("history:", get_history(5))
    print("stats:", get_stats())
