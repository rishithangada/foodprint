"""
Rich terminal display helpers for FoodPrint.
"""

from __future__ import annotations

import time
from typing import Any, Iterable

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text


console = Console()


def _value(result: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in result and result[key] not in (None, ""):
            return result[key]
    return default


def _risk_color(score: float) -> str:
    if score >= 7.5:
        return "bold red"
    if score >= 4.5:
        return "yellow"
    return "green"


def _risk_name(score: float) -> str:
    if score >= 7.5:
        return "HIGH"
    if score >= 4.5:
        return "MEDIUM"
    return "LOW"


def _risk_bar(score: float, width: int = 24) -> Text:
    filled = max(0, min(width, round((score / 10.0) * width)))
    color = _risk_color(score)
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("░" * (width - filled), style="grey23")
    return bar


def _risk_row(title: str, score: float, finding: str) -> Table:
    row = Table.grid(expand=True)
    row.add_column(ratio=2)
    row.add_column(ratio=3)
    row.add_column(justify="right", no_wrap=True)
    row.add_row(
        Text(title, style="bold white"),
        _risk_bar(score),
        Text(f"{score:.1f}  {_risk_name(score)}", style=_risk_color(score)),
    )
    row.add_row("", Text(finding, style="dim white"), "")
    return row


def _format_origins(origins: Iterable[Any]) -> str:
    formatted: list[str] = []
    for origin in list(origins)[:3]:
        if isinstance(origin, dict):
            country = origin.get("country") or origin.get("name") or "Unknown"
            percent = origin.get("percent") or origin.get("probability") or origin.get("score")
        elif isinstance(origin, (tuple, list)) and len(origin) >= 2:
            country, percent = origin[0], origin[1]
        else:
            continue

        try:
            pct = int(round(float(percent)))
        except (TypeError, ValueError):
            pct = 0
        formatted.append(f"{country} {pct}%")

    return " · ".join(formatted) if formatted else "Unknown origin probability"


def run_loading_sequence() -> None:
    steps = [
        ("scanning pesticide database...", 38),
        ("checking microplastic risk...", 30),
        ("tracing origin...", 26),
        ("computing contamination score...", 34),
    ]

    progress = Progress(
        SpinnerColumn(style="red"),
        TextColumn("[bold red]{task.description}"),
        BarColumn(bar_width=None, complete_style="red", finished_style="dark_red", pulse_style="red"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )
    with progress:
        for label, total in steps:
            task_id = progress.add_task(label, total=total)
            for _ in range(total):
                progress.advance(task_id)
                time.sleep(0.018)
            time.sleep(0.08)


def print_result(result_dict: dict[str, Any]) -> None:
    food = _value(result_dict, "food_name", "food", default="unknown food")
    store = _value(result_dict, "store", "store_name", default="unknown store")
    city = _value(result_dict, "city", default="unknown city")

    pesticide_score = float(_value(result_dict, "pesticide_score", default=0.0))
    microplastic_score = float(_value(result_dict, "microplastic_score", default=0.0))
    processing_score = float(_value(result_dict, "processing_score", default=0.0))
    overall_score = float(_value(result_dict, "overall_score", default=0.0))

    header = Text(f"FOODPRINT ANALYSIS — {food} @ {store} {city}", style="bold red")
    separator = Text("━" * 70, style="dark_red")
    thick_separator = Text("█" * 70, style="dark_red")
    overall = Text.assemble(
        ("OVERALL CONCERN: ", "bold white"),
        (f"{overall_score:.1f} / 10", _risk_color(overall_score)),
    )

    verdict = str(_value(result_dict, "verdict", default="No verdict generated."))
    verdict_lines = " ".join(verdict.split())
    if len(verdict_lines) > 96:
        midpoint = verdict_lines.rfind(" ", 0, 96)
        midpoint = midpoint if midpoint > 0 else 96
        verdict_lines = f"{verdict_lines[:midpoint]}\n{verdict_lines[midpoint + 1:]}"

    body = Group(
        header,
        separator,
        _risk_row(
            "PESTICIDE RISK",
            pesticide_score,
            str(_value(result_dict, "pesticide_detail", default="Residue risk estimated from available category data.")),
        ),
        Text(""),
        _risk_row(
            "MICROPLASTIC RISK",
            microplastic_score,
            str(_value(result_dict, "microplastic_detail", default="Packaging transfer risk estimated from material data.")),
        ),
        Text(""),
        _risk_row(
            "PROCESSING LEVEL",
            processing_score,
            str(_value(result_dict, "processing_detail", default="NOVA-style processing estimate based on food category.")),
        ),
        Text(""),
        Text.assemble(("ORIGIN LIKELY: ", "bold white"), (_format_origins(_value(result_dict, "origins", default=[])), "white")),
        thick_separator,
        overall,
        Text.assemble(("VERDICT:\n", "bold red"), (verdict_lines, "white")),
        Text("logged to food_log.db · foodprint v1.0", style="dim"),
    )

    console.print(
        Panel(
            body,
            border_style="red",
            box=box.HEAVY,
            padding=(1, 2),
            style="white on black",
        )
    )


def print_history(rows: list[dict[str, Any]]) -> None:
    table = Table(
        title=Text("FOODPRINT HISTORY", style="bold red"),
        box=box.HEAVY_HEAD,
        border_style="dark_red",
        header_style="bold red",
        show_lines=False,
    )
    table.add_column("date", style="dim white", no_wrap=True)
    table.add_column("food", style="white")
    table.add_column("store", style="white")
    table.add_column("overall score", justify="right")

    for row in rows:
        score = float(_value(row, "overall_score", "overall", default=0.0))
        table.add_row(
            str(_value(row, "date", "created_at", default="")),
            str(_value(row, "food", "food_name", default="")),
            str(_value(row, "store", "store_name", default="")),
            Text(f"{score:.1f}", style=_risk_color(score)),
        )

    if not rows:
        table.add_row("—", "No logged scans", "Run python foodprint.py", Text("—", style="dim"))

    console.print(table)


def print_stats(stats: dict[str, Any]) -> None:
    if not stats.get("total_scans"):
        console.print(Panel("No scans logged yet.", title="FOODPRINT STATS", border_style="red", style="white on black"))
        return

    table = Table.grid(padding=(0, 3))
    table.add_column(style="bold white")
    table.add_column(style="red")
    table.add_row("total scans", str(stats["total_scans"]))
    table.add_row("average concern", f"{float(stats['average_score']):.1f} / 10")
    table.add_row("highest concern", f"{stats['highest_food']} ({float(stats['highest_score']):.1f})")
    table.add_row("most scanned store", str(stats["top_store"]))

    console.print(
        Panel(
            table,
            title=Text("FOODPRINT STATS", style="bold red"),
            border_style="red",
            box=box.HEAVY,
            padding=(1, 2),
            style="white on black",
        )
    )
