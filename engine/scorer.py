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
        result.ewg_rank, result.pesticide_detail = _pesticide_detail(key, raw_pest, organic, store, state)
    else:
        result.ewg_rank = "No EWG data"
        result.pesticide_detail = _unknown_pesticide_detail(key, organic)

    # ── Microplastic score ───────────────────────────────────────────────────
    pkg_score  = PACKAGING_SCORES.get(packaging.lower(), 5.0)
    food_mod   = FOOD_MICRO_MODIFIER.get(key, 0.0)
    result.microplastic_score = min((pkg_score + food_mod) / 1.2, 10.0)
    result.microplastic_label = _label(result.microplastic_score)
    result.microplastic_detail = _microplastic_detail(key, packaging, city, state)

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
    result.verdict = _build_verdict(
        key, store, city, state, packaging, organic,
        result.overall_score, result.pesticide_score,
        result.microplastic_score, result.processing_score,
    )

    return result


# ── Rich text generators ─────────────────────────────────────────────────────

# Store sourcing profiles
_STORE_PROFILES: dict[str, str] = {
    "heb":          "H-E-B sources primarily from Texas and regional suppliers",
    "whole foods":  "Whole Foods requires stricter pesticide limits than USDA — but still not zero",
    "trader joe's": "Trader Joe's private-label produce sourcing varies widely by season",
    "walmart":      "Walmart sources from large-scale industrial farms with high volume turnover",
    "kroger":       "Kroger's Simple Truth organic line meets USDA organic, conventional varies",
    "costco":       "Costco bulk packaging means higher surface area exposure over longer storage",
    "target":       "Target's Good & Gather line has improved sourcing transparency since 2022",
    "aldi":         "ALDI sources produce internationally — country of origin varies by season",
    "publix":       "Publix sources from Florida and Southeast regional farms seasonally",
    "sprouts":      "Sprouts focuses on natural products but organic certification varies by item",
    "safeway":      "Safeway's O Organics line is USDA certified; conventional sourcing is standard",
    "fresh market": "The Fresh Market emphasizes local sourcing — pesticide protocols still vary",
}

# State-specific agricultural/contamination context
_STATE_CONTEXT: dict[str, str] = {
    "tx": "Texas has limited state pesticide regulation beyond federal EPA minimums",
    "ca": "California has stricter pesticide rules than federal — CDPR monitors residues",
    "fl": "Florida's warm climate requires heavier pesticide application year-round",
    "ny": "New York produce sourced locally benefits from cooler-climate lower pest pressure",
    "wa": "Washington state is a top apple and berry producer — high pesticide scrutiny",
    "or": "Oregon has above-average organic farmland — regional produce tends to be cleaner",
    "ga": "Georgia's peach and poultry industry uses significant agrochemical inputs",
    "il": "Illinois corn/soy country — glyphosate runoff affects local water and produce",
    "nc": "North Carolina is a major sweet potato and tobacco state — medium pesticide use",
    "az": "Arizona winter produce ships long distances, requiring post-harvest treatments",
    "co": "Colorado has growing organic farming sector — local sourcing increasingly available",
    "mi": "Michigan cherries and blueberries rank among highest-pesticide fruits nationally",
}

# Packaging × food-specific microplastic detail
def _microplastic_detail(food: str, packaging: str, city: str, state: str) -> str:
    pkg = packaging.lower()
    city_l = city.lower()

    water_cities = {"houston", "pittsburgh", "newark", "flint", "milwaukee", "baltimore"}
    water_note = f" Tap water in {city.title()} has documented contamination concerns — use filtered water when washing." if city_l in water_cities else ""

    combos = {
        ("plastic wrap",      "meat"):    "Plastic wrap on raw meat is especially risky — fat content accelerates microplastic absorption. Remove and transfer to glass immediately.",
        ("plastic wrap",      "produce"): "Plastic wrap clings directly to produce surface. Particles embed in the outer layers — peeling or scrubbing helps but doesn't eliminate risk.",
        ("plastic clamshell", "berries"): "Berries have high surface area and soft skin — microplastic particles from clamshell contact penetrate more deeply than with firm produce.",
        ("styrofoam",         "meat"):    "Styrofoam trays with meat are the worst-case scenario. Heat from the meat causes styrene leaching directly into fat tissue. Always transfer immediately.",
        ("styrofoam",         "produce"): "Styrofoam contact with acidic produce (tomatoes, citrus) accelerates styrene leaching significantly.",
        ("can",               "acidic"):  "BPA/BPS epoxy lining reacts with acidic contents — tomatoes, citrus juice, and vinegar-based foods have 2-3x higher leaching rates.",
        ("plastic bottle",    "water"):   "Bottled water averages 240 microplastic particles per liter (WHO 2019). Nanoplastics can cross the blood-brain barrier.",
        ("cardboard",         "frozen"):  "Frozen food cardboard often has PFAS-based moisture barrier coating. PFAS are persistent — they don't break down in the body.",
        ("glass",             "any"):     "Glass is the gold standard for zero microplastic transfer. Zero leaching regardless of temperature, acidity, or storage time.",
        ("plastic bag",       "produce"): "Produce bags generate static that attracts airborne microplastic fibers. Washing produce after removing from bag reduces particle load.",
    }

    food_cat = "meat" if food in {"chicken","beef","pork","lamb","turkey","salmon","tuna","fish","shrimp"} else \
               "berries" if food in {"strawberries","blueberries","raspberries","blackberries","cherries"} else \
               "acidic" if food in {"tomatoes","oranges","lemons","limes","vinegar"} else \
               "water" if food in {"bottled water","water"} else \
               "frozen" if food in {"frozen meal","ice cream"} else "produce"

    detail = combos.get((pkg, food_cat)) or combos.get((pkg, "any"))

    if detail:
        return detail + water_note

    generic = {
        "plastic wrap":      f"Direct plastic contact with {food} transfers nano-particles to the food surface. Transfer to glass or ceramic for storage.",
        "plastic clamshell": f"{food.title()} in plastic clamshells accumulates static charge that attracts airborne microplastic fibers during transport.",
        "plastic bag":       f"Plastic bag contact with {food} creates ongoing particle migration, especially if stored in a warm environment.",
        "plastic bottle":    "Plastic bottles shed particles into contents over time, worsening with heat exposure and repeated opening.",
        "plastic tray":      f"Plastic trays under {food} leach particles especially if the tray is heated (microwave, warm display case).",
        "styrofoam":         f"Styrofoam is the highest-risk packaging for {food}. Styrene is a possible carcinogen — always transfer contents immediately.",
        "can":               f"Canned {food} may contain BPA/BPS from epoxy lining. Risk increases if the can is dented or old.",
        "tetra pak":         f"Tetra Pak has a plastic inner layer — {food} stored long-term may absorb low levels of plasticizers.",
        "cardboard":         f"Cardboard is generally low risk for {food}. Check for waxy or moisture-resistant coating which may contain PFAS.",
        "glass":             f"Glass packaging for {food} carries essentially zero microplastic risk. Best available option.",
        "paper bag":         f"Paper bags are low risk for {food}. Minimal plastic exposure unless the bag has a plastic liner.",
        "none":              f"Fresh bulk {food} has no packaging contact. Main microplastic risk comes from ambient air, water used for washing, and soil.",
    }
    return generic.get(pkg, f"Packaging microplastic risk for {food} estimated from category averages.") + water_note


def _pesticide_detail(food: str, raw_score: float, organic: bool, store: str, state: str) -> tuple[str, str]:
    store_l = store.lower().strip()
    state_l = state.lower().strip()
    state_ctx = _STATE_CONTEXT.get(state_l, "")

    # Find store match
    store_note = ""
    for name, profile in _STORE_PROFILES.items():
        if name in store_l:
            store_note = profile
            break

    food_specific: dict[str, str] = {
        "strawberries":  "USDA found up to 22 different pesticide residues on a single strawberry sample in 2024. Bifenthrin and malathion are most prevalent.",
        "spinach":       "Spinach retains pesticides in its leaves due to surface texture. Permethrin and imidacloprid are commonly detected.",
        "kale":          "Kale tests positive for DCPA (Dacthal) — an EPA-designated possible human carcinogen — more than any other vegetable.",
        "peaches":       "Peach skin absorbs pesticides deeply — peeling reduces residue by ~50% but not to zero. Neonicotinoids are commonly found.",
        "apples":        "Apples receive some of the highest pesticide application rates of any fruit. Diphenylamine (DPA) is applied post-harvest in most US facilities.",
        "grapes":        "Imported grapes (Chile, Mexico) often carry fungicides not approved in the US. Check country of origin.",
        "blueberries":   "Wild blueberries have lower residue than cultivated. Cultivated blueberries in Michigan and NJ show high neonicotinoid presence.",
        "cherries":      "Sweet cherries from Washington state have among the highest pesticide residue rates of any tree fruit nationally.",
        "bell peppers":  "Bell peppers rank among the highest for acephate — an organophosphate linked to neurodevelopmental effects in children.",
        "celery":        "Celery has a high surface-to-volume ratio and no protective skin. Residues penetrate the entire stalk.",
        "tomatoes":      "Tomatoes used for commercial sauce receive heavy fungicide treatment. Fresh market tomatoes are moderately treated.",
        "potatoes":      "Potatoes are treated with chlorpropham post-harvest to prevent sprouting. This residue persists through storage.",
        "oats":          "Oats frequently test positive for glyphosate (Roundup) — used as a desiccant before harvest, not just a weed killer.",
        "wheat":         "Wheat is often sprayed with glyphosate just before harvest for uniform drying. Bread and pasta retain measurable residues.",
        "rice":          "US rice fields use heavy herbicide application. Arsenic contamination from soil is an additional concern in some regions.",
        "chicken":       "Conventionally raised chicken may contain chlorine wash residue (US practice banned in EU). Arsenic-based feed additives were phased out in 2015.",
        "beef":          "Conventional beef contains hormone residue (estradiol, zeranol) from growth promoters — not present in organic or grass-fed.",
        "salmon":        "Farmed salmon is treated with pesticides to control sea lice. Wild-caught has minimal pesticide exposure.",
        "shrimp":        "Imported shrimp (Thailand, Vietnam, India) frequently tests positive for antibiotics and pesticides not approved in the US.",
        "avocado":       "Avocados have thick skin that acts as a natural barrier. USDA testing finds almost zero residue on the flesh.",
        "onion":         "Onions have multiple paper-like layers and low water content — pesticides don't penetrate to the edible portion.",
        "corn":          "Most US corn is GMO and herbicide-resistant (Roundup Ready). Glyphosate residue is common in conventional corn products.",
    }

    base = food_specific.get(food, f"USDA testing shows {'elevated' if raw_score >= 6 else 'moderate' if raw_score >= 3.5 else 'low'} pesticide residue levels for {food}.")

    if organic:
        ewg = "EWG Dirty Dozen 2024" if raw_score / 0.25 >= 8 else "EWG Clean Fifteen 2024" if raw_score / 0.25 <= 2.5 else "EWG mid-range"
        detail = f"Organic certification reduces pesticide load by ~75%. {base}"
        if store_note:
            detail += f" Note: {store_note} — verify the organic label is USDA certified, not just 'natural.'"
    else:
        ewg = "EWG Dirty Dozen 2024" if raw_score >= 8 else "EWG Clean Fifteen 2024" if raw_score <= 2.5 else "EWG mid-range"
        detail = base
        if store_note:
            detail += f" {store_note}."
        if state_ctx:
            detail += f" {state_ctx}."

    return ewg, detail


def _unknown_pesticide_detail(food: str, organic: bool) -> str:
    if organic:
        return f"No specific EWG data for {food}, but organic certification guarantees synthetic pesticide use is prohibited during growth."
    return f"No specific EWG data for {food}. Estimated from closest food category. Consider checking EWG's full database for updates."


def _build_verdict(
    food: str, store: str, city: str, state: str, packaging: str,
    organic: bool, overall: float, pest: float, micro: float, proc: float,
) -> str:
    store_l  = store.lower().strip()
    pkg_l    = packaging.lower().strip()
    state_l  = state.lower().strip()

    # Store-specific action advice
    store_advice = ""
    if "whole foods" in store_l:
        store_advice = "Whole Foods' sourcing standards reduce but don't eliminate pesticide risk."
    elif "heb" in store_l:
        store_advice = "H-E-B's Texas-sourced produce is fresher but follows standard USDA pesticide limits."
    elif "walmart" in store_l or "sam's" in store_l:
        store_advice = "Large-volume retail sourcing means produce often travels farther and receives more post-harvest treatment."
    elif "trader joe" in store_l:
        store_advice = "Trader Joe's doesn't publish detailed sourcing data — origin varies significantly by season."
    elif "costco" in store_l:
        store_advice = "Costco bulk quantities mean longer home storage — contamination risk increases over time after purchase."
    elif "sprouts" in store_l or "fresh market" in store_l:
        store_advice = "Natural grocery stores emphasize clean sourcing but independently verify organic certifications when possible."

    # Packaging-specific action
    pkg_action = ""
    if "plastic" in pkg_l or "styrofoam" in pkg_l:
        pkg_action = f"Transfer {food} out of {packaging} packaging immediately — don't store or reheat in it."
    elif pkg_l == "can":
        pkg_action = f"Avoid heating canned {food} in the can. Transfer to glass or ceramic before warming."
    elif pkg_l == "glass":
        pkg_action = "Glass packaging is ideal — no further action needed on microplastic exposure."
    elif pkg_l == "cardboard":
        pkg_action = "Check if cardboard has a waxy or glossy inner coating — that indicates PFAS moisture barrier."

    # Organic-specific advice
    if organic:
        org_note = f"Organic {food} is a good call" if pest > 3.0 else f"Organic certification adds minimal benefit for {food} — it's inherently low-residue"
    else:
        org_note = f"Switching to organic {food} would reduce pesticide score from {pest:.1f} to ~{pest*0.25:.1f}" if pest >= 5.0 else f"Organic upgrade for {food} is optional at this risk level"

    # Regional water note
    state_water = {
        "tx": "Texas tap water quality varies significantly by city — Austin and Houston have different contamination profiles.",
        "fl": "Florida groundwater has documented PFAS and nitrate contamination in many regions.",
        "ca": "California's Central Valley water supply contains agricultural runoff including nitrates and pesticides.",
        "mi": "Michigan has ongoing PFAS contamination from industrial sites affecting municipal water in several cities.",
        "il": "Illinois municipal water in older cities may contain lead from aging pipes — use filtered water for washing produce.",
    }
    water_note = state_water.get(state_l, "")

    # Build the verdict sentence by sentence
    parts = []

    if overall >= 7.5:
        parts.append(f"High cumulative exposure risk for {food} from {store.title() if store else 'this source'}.")
        parts.append(org_note + "." if not organic else org_note + " — continue.")
        if pkg_action: parts.append(pkg_action)
        parts.append("Wash under cold running water for 45+ seconds. Scrub firm produce with a brush.")
        if store_advice: parts.append(store_advice)
        if water_note: parts.append(water_note)

    elif overall >= 4.5:
        parts.append(f"Moderate concern for {food}.")
        parts.append(org_note + ".")
        if pkg_action: parts.append(pkg_action)
        parts.append("Rinse thoroughly. " + ("Don't microwave in this container." if "plastic" in pkg_l or "styrofoam" in pkg_l else "Packaging risk is manageable."))
        if store_advice: parts.append(store_advice)

    else:
        parts.append(f"{food.title()} is a lower-risk choice at this profile.")
        parts.append(org_note + ".")
        if pkg_action: parts.append(pkg_action)
        if store_advice: parts.append(store_advice)
        if water_note: parts.append(water_note)
        parts.append("Standard food safety practices are sufficient.")

    return " ".join(parts)
