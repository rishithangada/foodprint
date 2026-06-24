"""
External food-data API integration for FoodPrint.

Two data sources:
  - Open Food Facts (packaging, ingredients, processing level, origin, brands)
  - USDA FoodData Central (pesticide-relevant fields)

Every network call is async (httpx), has a 10s timeout, falls back to None on
any error, and is cached to engine/.cache/ as JSON with a 1-week TTL.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CACHE_DIR = Path(__file__).resolve().parent / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL = 7 * 24 * 60 * 60  # 1 week, in seconds
TIMEOUT = 10.0  # seconds

USDA_API_KEY = "DEMO_KEY"

OFF_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

USER_AGENT = "FoodPrint/0.1 (food-footprint research tool)"

NOVA_LABELS = {
    1: "Unprocessed / minimally processed",
    2: "Processed culinary ingredient",
    3: "Processed food",
    4: "Ultra-processed food",
}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(namespace: str, food_name: str) -> str:
    """Stable, filesystem-safe cache key for a (source, food) pair."""
    norm = re.sub(r"\s+", "_", food_name.strip().lower())
    norm = re.sub(r"[^a-z0-9_]", "", norm)
    digest = hashlib.sha1(f"{namespace}:{food_name.strip().lower()}".encode()).hexdigest()[:8]
    return f"{namespace}_{norm}_{digest}"


def _cache_path(namespace: str, food_name: str) -> Path:
    return CACHE_DIR / f"{_cache_key(namespace, food_name)}.json"


def _read_cache(namespace: str, food_name: str) -> Optional[dict[str, Any]]:
    """Return cached payload if present and not expired, else None."""
    path = _cache_path(namespace, food_name)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    if time.time() - raw.get("_cached_at", 0) > CACHE_TTL:
        return None
    return raw.get("data")


def _write_cache(namespace: str, food_name: str, data: Optional[dict[str, Any]]) -> None:
    """Persist a payload (including None misses) with a timestamp."""
    path = _cache_path(namespace, food_name)
    try:
        path.write_text(json.dumps({"_cached_at": time.time(), "data": data}, indent=2))
    except OSError:
        pass  # caching is best-effort, never fatal


# ---------------------------------------------------------------------------
# Open Food Facts
# ---------------------------------------------------------------------------

async def fetch_openfoodfacts(food_name: str) -> Optional[dict[str, Any]]:
    """
    Look up a food on Open Food Facts and return a cleaned dict:

        {
          "source": "openfoodfacts",
          "product_name": str,
          "brands": [str, ...],
          "packaging": [str, ...],
          "ingredients": [str, ...],
          "nova_group": int | None,
          "nova_label": str | None,
          "countries": [str, ...],
          "labels": [str, ...],          # e.g. organic / fair-trade tags
          "off_id": str | None,
        }

    Returns None on any error or if nothing useful is found.
    """
    cached = _read_cache("off", food_name)
    if cached is not None:
        return cached

    params = {
        "search_terms": food_name,
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page_size": 5,
        "fields": (
            "product_name,brands_tags,packaging_tags,ingredients_text,"
            "nova_group,countries_tags,labels_tags,code"
        ),
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(OFF_SEARCH_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError, json.JSONDecodeError):
        # Transient failure (timeout, 5xx, bad body): do NOT cache, so the
        # next call retries once the service recovers.
        return None

    products = payload.get("products") or []
    product = _pick_best_off_product(products)
    if not product:
        _write_cache("off", food_name, None)
        return None

    nova = product.get("nova_group")
    try:
        nova = int(nova) if nova not in (None, "") else None
    except (TypeError, ValueError):
        nova = None

    result = {
        "source": "openfoodfacts",
        "product_name": product.get("product_name") or food_name,
        "brands": _clean_tags(product.get("brands_tags")),
        "packaging": _clean_tags(product.get("packaging_tags")),
        "ingredients": _split_ingredients(product.get("ingredients_text")),
        "nova_group": nova,
        "nova_label": NOVA_LABELS.get(nova),
        "countries": _clean_tags(product.get("countries_tags")),
        "labels": _clean_tags(product.get("labels_tags")),
        "off_id": product.get("code"),
    }

    _write_cache("off", food_name, result)
    return result


def _pick_best_off_product(products: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Prefer the first product that actually carries a usable name."""
    for product in products:
        if product.get("product_name"):
            return product
    return products[0] if products else None


def _clean_tags(tags: Any) -> list[str]:
    """Turn OFF tag lists (e.g. 'en:organic') into clean human strings."""
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        # strip 'en:' / 'fr:' language prefixes, normalise dashes
        cleaned = re.sub(r"^[a-z]{2}:", "", tag).replace("-", " ").strip()
        if cleaned:
            out.append(cleaned)
    return out


def _split_ingredients(text: Any) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    parts = re.split(r"[,;]", text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# USDA FoodData Central
# ---------------------------------------------------------------------------

async def fetch_usda_pesticides(food_name: str) -> Optional[dict[str, Any]]:
    """
    Look up a food on USDA FoodData Central and return pesticide-relevant
    context where available:

        {
          "source": "usda_fdc",
          "fdc_id": int | None,
          "description": str,
          "data_type": str,
          "food_category": str | None,
          "is_organic": bool,
          "pesticide_nutrients": [ {name, amount, unit}, ... ],
        }

    USDA does not expose raw pesticide-residue values through this endpoint,
    so we surface the closest available signals: declared food category,
    organic labelling in the description, and any nutrient rows that mention
    pesticide / residue terms. Returns None on any error.
    """
    cached = _read_cache("usda", food_name)
    if cached is not None:
        return cached

    params = {
        "api_key": USDA_API_KEY,
        "query": food_name,
        "pageSize": 5,
        "dataType": "Foundation,SR Legacy,Survey (FNDDS)",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(USDA_SEARCH_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError, json.JSONDecodeError):
        # Transient failure (timeout, 5xx, bad body): do NOT cache, so the
        # next call retries once the service recovers.
        return None

    foods = payload.get("foods") or []
    if not foods:
        _write_cache("usda", food_name, None)
        return None

    food = foods[0]
    description = (food.get("description") or food_name).strip()

    pesticide_terms = ("pesticide", "residue", "glyphosate", "atrazine", "chlorpyrifos")
    pesticide_nutrients = []
    for nutrient in food.get("foodNutrients") or []:
        name = str(nutrient.get("nutrientName", "")).lower()
        if any(term in name for term in pesticide_terms):
            pesticide_nutrients.append({
                "name": nutrient.get("nutrientName"),
                "amount": nutrient.get("value"),
                "unit": nutrient.get("unitName"),
            })

    result = {
        "source": "usda_fdc",
        "fdc_id": food.get("fdcId"),
        "description": description,
        "data_type": food.get("dataType"),
        "food_category": food.get("foodCategory"),
        "is_organic": "organic" in description.lower(),
        "pesticide_nutrients": pesticide_nutrients,
    }

    _write_cache("usda", food_name, result)
    return result


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

async def fetch_all(food_name: str) -> dict[str, Optional[dict[str, Any]]]:
    """Fetch both sources concurrently."""
    off, usda = await asyncio.gather(
        fetch_openfoodfacts(food_name),
        fetch_usda_pesticides(food_name),
    )
    return {"openfoodfacts": off, "usda": usda}


if __name__ == "__main__":
    import sys

    name = " ".join(sys.argv[1:]) or "strawberries"
    print(json.dumps(asyncio.run(fetch_all(name)), indent=2))
