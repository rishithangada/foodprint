#!/usr/bin/env python3
"""
FoodPrint command-line interface.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
from typing import Any

import questionary
from dotenv import load_dotenv

from engine.database import get_history, get_stats, init_db, save_entry
from engine.display import console, print_history, print_result, print_stats, run_loading_sequence
from engine.origin import detect_origin
from engine.scorer import score_food


APP_DIR = Path(__file__).resolve().parent
PACKAGING_CHOICES = [
    "plastic wrap",
    "plastic clamshell",
    "cardboard",
    "glass",
    "none",
    "unknown",
]


def _prompt_required(message: str, default: str | None = None) -> str:
    while True:
        answer = questionary.text(message, default=default or "").ask()
        if answer is None:
            raise KeyboardInterrupt
        answer = answer.strip()
        if answer:
            return answer
        console.print("[red]Required.[/red]")


def collect_inputs() -> dict[str, Any]:
    food_name = _prompt_required("Food name:")
    store = _prompt_required("Store name:")
    city = _prompt_required("City:")
    state = _prompt_required("State:")
    country = _prompt_required("Country:", default="USA")
    packaging = questionary.select("Packaging type:", choices=PACKAGING_CHOICES, default="unknown").ask()
    if packaging is None:
        raise KeyboardInterrupt
    organic = questionary.confirm("Organic?", default=False).ask()
    if organic is None:
        raise KeyboardInterrupt

    return {
        "food_name": food_name,
        "store": store,
        "city": city,
        "state": state,
        "country": country,
        "packaging": packaging,
        "organic": bool(organic),
    }


def log_result(result: dict[str, Any]) -> None:
    origin_primary = result["origins"][0][0] if result.get("origins") else "Unknown"
    save_entry({**result, "origin_primary": origin_primary})


def show_history() -> None:
    rows = [
        {
            "date": row.get("logged_at", ""),
            "food": row.get("food_name", ""),
            "store": row.get("store", ""),
            "overall_score": row.get("overall_score", 0),
        }
        for row in get_history(20)
    ]
    print_history(rows)


def show_stats() -> None:
    stats = get_stats()
    highest = stats["most_concerning"][0] if stats["most_concerning"] else {}
    top_store = stats["top_store"] or {}
    print_stats(
        {
            "total_scans": stats["total_entries"],
            "average_score": stats["avg_overall_score"] or 0,
            "highest_food": highest.get("food_name", "n/a"),
            "highest_score": highest.get("avg_overall_score", 0),
            "top_store": top_store.get("store", "n/a"),
        }
    )


def run_interactive() -> None:
    console.print("[bold red]FOODPRINT[/bold red] [dim]contamination scanner v1.0[/dim]")
    inputs = collect_inputs()
    run_loading_sequence()
    scored = score_food(**inputs)
    result = asdict(scored)
    result["origins"] = detect_origin(
        inputs["food_name"],
        inputs["store"],
        city=inputs["city"],
        state=inputs["state"],
    )
    log_result(result)
    print_result(result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FoodPrint contamination scanner")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("history", "stats"),
        help="show the last 20 scans or aggregate scanner stats",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv(APP_DIR / ".env")
    init_db()
    args = parse_args()
    try:
        if args.command == "history":
            show_history()
        elif args.command == "stats":
            show_stats()
        else:
            run_interactive()
    except KeyboardInterrupt:
        console.print("\n[dim]scan aborted[/dim]")


if __name__ == "__main__":
    main()
