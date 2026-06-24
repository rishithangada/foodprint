"""
scorer.py — Core contamination scoring engine for FoodPrint.

Combines EWG pesticide data, microplastic risk by packaging/food type,
and processing level into a unified 0-10 concern score.
"""

from __future__ import annotations
from dataclasses import dataclass, field

# ── EWG Dirty Dozen / Clean Fifteen 2024 ────────────────────────────────────
# Pesticide score: 10 = worst (top dirty dozen), 1 = cleanest
EWG_SCORES: dict[str, float] = {
    # Dirty Dozen (high risk)
    "strawberries": 9.8, "spinach": 9.5, "kale": 9.2, "collard greens": 9.2,
    "mustard greens": 9.2, "peaches": 9.0, "pears": 8.8, "nectarines": 8.7,
    "apples": 8.6, "grapes": 8.5, "bell peppers": 8.4, "hot peppers": 8.4,
    "cherries": 8.2, "blueberries": 8.0, "green beans": 7.8,
    # Mid range
    "tomatoes": 6.5, "celery": 6.8, "potatoes": 6.2, "lettuce": 6.0,
    "cucumber": 5.5, "snap peas": 5.2, "raspberries": 7.5, "blackberries": 7.2,
    "oranges": 5.8, "tangerines": 5.5, "lemons": 4.8, "limes": 4.5,
    "carrots": 5.0, "squash": 5.2, "broccoli": 4.5, "cabbage": 4.0,
    "wheat": 5.5, "oats": 6.0, "rice": 4.5, "corn": 3.5,
    # Animal products
    "chicken": 3.0, "beef": 2.5, "pork": 2.5, "salmon": 2.0,
    "tuna": 2.0, "shrimp": 3.5, "eggs": 2.5, "milk": 2.0,
    "cheese": 2.0, "butter": 2.5, "yogurt": 2.0,
    # Clean Fifteen (low risk)
    "avocado": 1.2, "sweet corn": 1.5, "pineapple": 1.3, "onion": 1.2,
    "papaya": 1.5, "sweet peas frozen": 1.8, "asparagus": 1.5,
    "honeydew melon": 2.0, "kiwi": 2.2, "cabbage": 1.5, "mushrooms": 1.8,
    "mango": 1.5, "sweet potato": 2.0, "watermelon": 2.5, "banana": 2.2,
    # Pantry
    "coffee": 4.5, "tea": 5.0, "bread": 3.0, "pasta": 2.5,
    "olive oil": 2.0, "vegetable oil": 3.5, "soy sauce": 3.0,
}

# ── Microplastic risk by packaging type ─────────────────────────────────────
PACKAGING_SCORES: dict[str, float] = {
    "plastic wrap":       8.5,
    "plastic clamshell":  8.0,
    "plastic bag":        7.5,
    "plastic bottle":     7.0,
    "plastic tray":       7.0,
    "styrofoam":          9.0,
    "can":                4.0,   # BPA lining risk
    "tetra pak":          5.0,
    "cardboard":          2.5,
    "glass":              1.0,
    "paper bag":          1.5,
    "none":               1.0,   # fresh bulk produce
    "unknown":            5.0,
}

# ── Additional microplastic risk by food type ───────────────────────────────
# Some foods absorb/carry more microplastics regardless of packaging
FOOD_MICRO_MODIFIER: dict[str, float] = {
    "sea salt": 3.0, "honey": 2.0, "beer": 2.5, "bottled water": 4.0,
    "tap water": 2.0, "seafood": 3.0, "shrimp": 3.5, "mussels": 4.0,
    "clams": 4.0, "oysters": 4.0, "fish": 2.5, "salmon": 2.0, "tuna": 2.0,
    # Highly processed foods often use plastic-lined equipment
    "chips": 2.0, "crackers": 1.5, "cookies": 1.5, "cereal": 1.0,
}

# ── Organic modifier ─────────────────────────────────────────────────────────
ORGANIC_PESTICIDE_REDUCTION = 0.25   # organic = 25% of conventional score

# ── Processing level risk (NOVA classification proxy) ───────────────────────
PROCESSING_SCORES: dict[str, float] = {
    # Whole / minimally processed
    "fresh fruit": 1.0, "fresh vegetable": 1.0, "fresh meat": 2.0,
    "eggs": 1.5, "milk": 2.0, "dried beans": 1.5, "rice": 2.0,
    "fresh fish": 2.0, "nuts": 1.5,
    # Processed ingredients
    "oil": 3.0, "butter": 3.5, "flour": 3.0, "cheese": 4.0,
    "yogurt": 3.5, "bread": 5.0, "pasta": 4.0,
    # Ultra-processed
    "chips": 9.0, "soda": 9.5, "fast food": 9.0, "candy": 9.0,
    "frozen meal": 8.0, "instant noodles": 8.5, "hot dog": 8.5,
    "cereal": 7.0, "crackers": 7.5, "cookies": 8.0, "ice cream": 7.0,
    "protein bar": 7.5, "energy drink": 9.0,
}

FOOD_TYPE_MAP: dict[str, str] = {
    # fruit → fresh fruit
    **{f: "fresh fruit" for f in [
        "strawberries","blueberries","raspberries","blackberries","cherries",
        "peaches","nectarines","pears","apples","grapes","oranges","lemons",
        "limes","mango","pineapple","watermelon","avocado","banana","kiwi",
        "papaya","honeydew melon","tangerines",
    ]},
    # vegetables → fresh vegetable
    **{f: "fresh vegetable" for f in [
        "spinach","kale","lettuce","tomatoes","bell peppers","hot peppers",
        "cucumbers","celery","carrots","broccoli","cabbage","potatoes",
        "sweet potato","onion","garlic","asparagus","green beans",
        "snap peas","corn","squash","mushrooms","collard greens",
        "mustard greens",
    ]},
    **{f: "fresh meat" for f in ["chicken","beef","pork","lamb","turkey"]},
    **{f: "fresh fish" for f in ["salmon","tuna","shrimp","fish","seafood",
                                  "mussels","clams","oysters"]},
    "eggs": "eggs", "milk": "milk", "cheese": "cheese", "yogurt": "yogurt",
    "butter": "butter", "bread": "bread", "pasta": "pasta", "rice": "rice",
    "oats": "rice", "flour": "flour", "olive oil": "oil",
    "coffee": "rice", "tea": "rice",
    "chips": "chips", "crackers": "crackers", "cookies": "cookies",
    "cereal": "cereal", "ice cream": "ice cream",
}


@dataclass
class FoodScore:
    food_name:          str
    store:              str
    city:               str
    state:              str
    country:            str
    packaging:          str
    organic:            bool

    pesticide_score:    float = 0.0
    microplastic_score: float = 0.0
    processing_score:   float = 0.0
    overall_score:      float = 0.0

    pesticide_label:    str   = ""
    microplastic_label: str   = ""
    processing_label:   str   = ""
    overall_label:      str   = ""

    pesticide_detail:   str   = ""
    microplastic_detail:str   = ""
    verdict:            str   = ""

    origins:            list  = field(default_factory=list)
    ewg_rank:           str   = ""


def _label(score: float) -> str:
    if score >= 7.5: return "HIGH"
    if score >= 4.5: return "MODERATE"
    if score >= 2.5: return "LOW"
    return "MINIMAL"


def _normalize(name: str) -> str:
    return name.lower().strip().rstrip("s") if name.endswith("ies") \
        else name.lower().strip()


def score_food(
    food_name: str,
    store: str,
    city: str,
    state: str,
    country: str = "USA",
    packaging: str = "unknown",
    organic: bool = False,
) -> FoodScore:
    result = FoodScore(
        food_name=food_name, store=store, city=city,
        state=state, country=country, packaging=packaging, organic=organic,
    )

    key = food_name.lower().strip()

    # ── Pesticide score ──────────────────────────────────────────────────────
    raw_pest = EWG_SCORES.get(key, 5.0)  # default mid-range if unknown
    if organic:
        raw_pest *= ORGANIC_PESTICIDE_REDUCTION
    result.pesticide_score = min(raw_pest, 10.0)
    result.pesticide_label = _label(result.pesticide_score)

    if key in EWG_SCORES:
        if raw_pest >= 8.0:
            result.ewg_rank    = "EWG Dirty Dozen 2024"
            result.pesticide_detail = f"Up to 22+ pesticide residues found by USDA testing"
        elif raw_pest <= 2.5:
            result.ewg_rank    = "EWG Clean Fifteen 2024"
            result.pesticide_detail = "Among the lowest pesticide residue foods tested"
        else:
            result.ewg_rank    = "EWG mid-range"
            result.pesticide_detail = "Moderate pesticide presence detected in USDA sampling"
    else:
        result.pesticide_detail = "Limited EWG data — estimated from food category"

    # ── Microplastic score ───────────────────────────────────────────────────
    pkg_score  = PACKAGING_SCORES.get(packaging.lower(), 5.0)
    food_mod   = FOOD_MICRO_MODIFIER.get(key, 0.0)
    result.microplastic_score = min((pkg_score + food_mod) / 1.2, 10.0)
    result.microplastic_label = _label(result.microplastic_score)

    pkg_notes = {
        "plastic wrap":      "direct plastic contact transfers nano-particles to food surface",
        "plastic clamshell": "surface contact + static charge attracts particles",
        "styrofoam":         "highest leaching risk especially with acidic or hot foods",
        "glass":             "lowest microplastic transfer risk",
        "cardboard":         "minimal transfer — some PFAS lining possible in waxed versions",
        "can":               "BPA/epoxy lining may leach — microplastic risk is lower",
    }
    result.microplastic_detail = pkg_notes.get(
        packaging.lower(),
        "packaging microplastic transfer estimated from category average"
    )

    # ── Processing score ─────────────────────────────────────────────────────
    food_type = FOOD_TYPE_MAP.get(key, "fresh fruit")
    result.processing_score = PROCESSING_SCORES.get(food_type, 4.0)
    result.processing_label = _label(result.processing_score)

    # ── Overall score (weighted) ─────────────────────────────────────────────
    result.overall_score = round(
        (result.pesticide_score    * 0.45 +
         result.microplastic_score * 0.35 +
         result.processing_score   * 0.20),
        1
    )
    result.overall_label = _label(result.overall_score)

    # ── Verdict ──────────────────────────────────────────────────────────────
    if result.overall_score >= 7.5:
        result.verdict = (
            f"{'Buy organic' if not organic else 'Limit consumption'} and wash under "
            f"running water for 30+ seconds. Switch to glass or cardboard packaging "
            f"where possible. High cumulative exposure risk with regular consumption."
        )
    elif result.overall_score >= 4.5:
        result.verdict = (
            f"Moderate concern. {'Organic would reduce pesticide risk significantly.' if not organic else 'Organic is a good call here.'} "
            f"Rinse thoroughly. {'Avoid microwaving in this packaging.' if 'plastic' in packaging.lower() else 'Packaging risk is manageable.'}"
        )
    else:
        result.verdict = (
            f"Lower risk food. {'Organic adds minimal additional benefit here.' if organic else 'Organic not critical for this item.'} "
            f"Standard food safety practices are sufficient."
        )

    return result
