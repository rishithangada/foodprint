"""
Heuristic origin detection for FoodPrint.

Given a food, store, location and month, estimate where the item most likely
came from. This is a probabilistic model built from two hand-curated tables:

  - SEASONAL_ORIGINS: which regions supply each food in each month (US market).
  - STORE_PROFILES:   how each retailer skews sourcing (domestic vs import,
                      organic, regional).

detect_origin() blends the two and returns the top 3 (region, probability%)
with a one-line sourcing note.
"""

from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Month helpers
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}


def _norm_month(month) -> int:
    """Accept an int (1-12) or a name; default to current month on failure."""
    if isinstance(month, int) and 1 <= month <= 12:
        return month
    if isinstance(month, str):
        key = month.strip().lower()
        if key.isdigit() and 1 <= int(key) <= 12:
            return int(key)
        if key[:3] in _MONTHS:
            return _MONTHS[key[:3]]
    from datetime import date
    return date.today().month


# ---------------------------------------------------------------------------
# Seasonal sourcing table
#
# Each food maps month-ranges -> {region: weight}. Weights are relative and
# get normalised later. Ranges are inclusive and may wrap the year-end.
# ---------------------------------------------------------------------------

SEASONAL_ORIGINS: dict[str, list[dict]] = {
    "strawberries": [
        {"months": (1, 4), "sources": {"Mexico": 70, "California (USA)": 30}},
        {"months": (5, 9), "sources": {"California (USA)": 80, "Oregon (USA)": 20}},
        {"months": (10, 12), "sources": {"Florida (USA)": 45, "Mexico": 55}},
    ],
    "blueberries": [
        {"months": (1, 3), "sources": {"Chile": 55, "Peru": 30, "Mexico": 15}},
        {"months": (4, 5), "sources": {"Mexico": 50, "Florida (USA)": 50}},
        {"months": (6, 8), "sources": {"Michigan (USA)": 35, "Oregon (USA)": 35, "New Jersey (USA)": 30}},
        {"months": (9, 12), "sources": {"Peru": 60, "Argentina": 40}},
    ],
    "spinach": [
        {"months": (1, 12), "sources": {"California (USA)": 60, "Arizona (USA)": 30, "Mexico": 10}},
    ],
    "apples": [
        {"months": (1, 7), "sources": {"Washington (USA)": 80, "New Zealand": 20}},
        {"months": (8, 12), "sources": {"Washington (USA)": 70, "Michigan (USA)": 30}},
    ],
    "grapes": [
        {"months": (1, 4), "sources": {"Chile": 60, "Peru": 40}},
        {"months": (5, 6), "sources": {"Mexico": 70, "California (USA)": 30}},
        {"months": (7, 11), "sources": {"California (USA)": 85, "Washington (USA)": 15}},
        {"months": (12, 12), "sources": {"Chile": 50, "Peru": 50}},
    ],
    "tomatoes": [
        {"months": (1, 5), "sources": {"Mexico": 70, "Florida (USA)": 30}},
        {"months": (6, 10), "sources": {"California (USA)": 50, "Local greenhouse": 50}},
        {"months": (11, 12), "sources": {"Mexico": 75, "Florida (USA)": 25}},
    ],
    "lettuce": [
        {"months": (1, 3), "sources": {"Arizona (USA)": 60, "California (USA)": 25, "Mexico": 15}},
        {"months": (4, 11), "sources": {"California (USA)": 80, "Local (USA)": 20}},
        {"months": (12, 12), "sources": {"Arizona (USA)": 60, "Mexico": 40}},
    ],
    "peppers": [
        {"months": (1, 5), "sources": {"Mexico": 75, "Netherlands": 25}},
        {"months": (6, 10), "sources": {"California (USA)": 55, "Local greenhouse": 45}},
        {"months": (11, 12), "sources": {"Mexico": 80, "Florida (USA)": 20}},
    ],
    "chicken": [
        {"months": (1, 12), "sources": {"USA (domestic)": 92, "Regional farm (USA)": 8}},
    ],
    "beef": [
        {"months": (1, 12), "sources": {"USA (domestic)": 80, "Australia": 12, "Canada": 8}},
    ],
    "salmon": [
        {"months": (1, 12), "sources": {"Norway (farmed)": 35, "Chile (farmed)": 35, "Alaska (USA, wild)": 30}},
    ],
    "rice": [
        {"months": (1, 12), "sources": {"Arkansas (USA)": 45, "California (USA)": 25, "Thailand": 15, "India": 15}},
    ],
    "bread": [
        {"months": (1, 12), "sources": {"Local bakery (USA)": 55, "USA (national brand)": 45}},
    ],
    "eggs": [
        {"months": (1, 12), "sources": {"USA (domestic)": 90, "Regional farm (USA)": 10}},
    ],
    "milk": [
        {"months": (1, 12), "sources": {"USA (domestic)": 95, "Regional dairy (USA)": 5}},
    ],
    "cheese": [
        {"months": (1, 12), "sources": {"Wisconsin (USA)": 50, "California (USA)": 30, "Europe (imported)": 20}},
    ],
    "coffee": [
        {"months": (1, 12), "sources": {"Colombia": 30, "Brazil": 30, "Ethiopia": 20, "Guatemala": 20}},
    ],
    "avocado": [
        {"months": (1, 12), "sources": {"Mexico": 80, "California (USA)": 15, "Peru": 5}},
    ],
    "banana": [
        {"months": (1, 12), "sources": {"Ecuador": 35, "Guatemala": 30, "Costa Rica": 20, "Colombia": 15}},
    ],
    "orange": [
        {"months": (1, 6), "sources": {"Florida (USA)": 55, "California (USA)": 45}},
        {"months": (7, 10), "sources": {"South Africa": 50, "California (USA)": 50}},
        {"months": (11, 12), "sources": {"Florida (USA)": 60, "California (USA)": 40}},
    ],
}

# Common aliases -> canonical key
_ALIASES = {
    "strawberry": "strawberries",
    "blueberry": "blueberries",
    "apple": "apples",
    "grape": "grapes",
    "tomato": "tomatoes",
    "bell pepper": "peppers",
    "bell peppers": "peppers",
    "pepper": "peppers",
    "egg": "eggs",
    "bananas": "banana",
    "avocados": "avocado",
    "oranges": "orange",
    "ground beef": "beef",
    "steak": "beef",
    "chicken breast": "chicken",
}


# ---------------------------------------------------------------------------
# Store sourcing profiles
#
# Each profile boosts/penalises sources by characteristic. Multipliers are
# applied to the seasonal weights before re-normalising.
# ---------------------------------------------------------------------------

STORE_PROFILES: dict[str, dict] = {
    "whole foods": {
        "note": "skews domestic, organic & local",
        "domestic_boost": 1.4,
        "import_boost": 0.7,
        "local_boost": 1.6,
    },
    "walmart": {
        "note": "high volume, more international sourcing",
        "domestic_boost": 0.85,
        "import_boost": 1.4,
        "local_boost": 0.7,
    },
    "heb": {
        "note": "strong regional Texas / Mexico supplier base",
        "domestic_boost": 1.15,
        "import_boost": 1.0,
        "local_boost": 1.5,
        "region_boost": {"Texas": 1.8, "Mexico": 1.3, "Local": 1.5},
    },
    "costco": {
        "note": "mixed domestic/import, bulk contracts",
        "domestic_boost": 1.0,
        "import_boost": 1.1,
        "local_boost": 0.8,
    },
    "trader joes": {
        "note": "private-label, mixed domestic/import",
        "domestic_boost": 1.1,
        "import_boost": 1.05,
        "local_boost": 0.9,
    },
    "kroger": {
        "note": "national chain, balanced sourcing",
        "domestic_boost": 1.05,
        "import_boost": 1.0,
        "local_boost": 1.0,
    },
}

_DEFAULT_PROFILE = {
    "note": "generic retailer assumptions",
    "domestic_boost": 1.0,
    "import_boost": 1.0,
    "local_boost": 1.0,
}


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def _is_domestic(region: str) -> bool:
    r = region.lower()
    return "usa" in r or "(usa" in r or "local" in r


def _is_local(region: str) -> bool:
    return "local" in region.lower()


def _months_match(month: int, window: tuple[int, int]) -> bool:
    start, end = window
    if start <= end:
        return start <= month <= end
    # wrap-around window (e.g. Dec-Feb)
    return month >= start or month <= end


def _canonical(food_name: str) -> Optional[str]:
    key = food_name.strip().lower()
    if key in SEASONAL_ORIGINS:
        return key
    if key in _ALIASES:
        return _ALIASES[key]
    # loose contains match (e.g. "organic strawberries 1lb")
    for canon in SEASONAL_ORIGINS:
        if canon in key:
            return canon
    for alias, canon in _ALIASES.items():
        if alias in key:
            return canon
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_origin(
    food_name: str,
    store: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    month=None,
) -> list[tuple[str, float, str]]:
    """
    Estimate likely origins for a food.

    Returns a list of up to 3 tuples: (region, probability_percent, note),
    sorted by probability descending. Returns a single 'Unknown' entry when
    the food is not in the seasonal table.
    """
    canon = _canonical(food_name)
    month_n = _norm_month(month)
    store_key = (store or "").strip().lower()
    profile = STORE_PROFILES.get(store_key, _DEFAULT_PROFILE)

    if canon is None:
        return [(
            "Unknown",
            0.0,
            f"No seasonal sourcing data for '{food_name}'.",
        )]

    # 1. Find the seasonal window matching the month.
    windows = SEASONAL_ORIGINS[canon]
    weights: dict[str, float] = {}
    for entry in windows:
        if _months_match(month_n, entry["months"]):
            for region, w in entry["sources"].items():
                weights[region] = weights.get(region, 0.0) + float(w)
    if not weights:
        # fall back to the first window if month logic missed
        for region, w in windows[0]["sources"].items():
            weights[region] = float(w)

    # 2. Apply store profile multipliers.
    region_boost = profile.get("region_boost", {})
    for region in list(weights):
        mult = 1.0
        if _is_domestic(region):
            mult *= profile["domestic_boost"]
        else:
            mult *= profile["import_boost"]
        if _is_local(region):
            mult *= profile["local_boost"]
        # store-specific region nudges (e.g. HEB + Texas/Mexico)
        for needle, boost in region_boost.items():
            if needle.lower() in region.lower():
                mult *= boost
        # local-knowledge nudge: a state match boosts that region
        if state and state.strip().lower() in region.lower():
            mult *= 1.5
        weights[region] *= mult

    # 3. Normalise to percentages.
    total = sum(weights.values()) or 1.0
    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)

    where = ", ".join(p for p in (city, state) if p) or "your area"
    note = f"{store or 'Store'} in {where}, {_month_name(month_n)}: {profile['note']}."

    results = []
    for region, w in ranked[:3]:
        pct = round(100.0 * w / total, 1)
        results.append((region, pct, note))
    return results


def _month_name(n: int) -> str:
    return [
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ][n]


if __name__ == "__main__":
    import sys

    food = sys.argv[1] if len(sys.argv) > 1 else "strawberries"
    store = sys.argv[2] if len(sys.argv) > 2 else "Whole Foods"
    for region, pct, note in detect_origin(food, store, city="Austin", state="Texas", month=3):
        print(f"{pct:5.1f}%  {region}")
    print("note:", note)
