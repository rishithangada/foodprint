# FoodPrint

A contamination scanner that tells you what's actually in your food — pesticide residues, microplastic exposure risk, and processing level — based on what you ate, where you bought it, and how it was packaged.

![CLI demo](https://img.shields.io/badge/python-3.11+-red?style=flat-square) ![license](https://img.shields.io/badge/license-MIT-black?style=flat-square)

---

## What it does

You enter a food item, the store you bought it from, your city/state, and packaging type. FoodPrint runs three independent risk assessments:

| Signal | Source | Weight |
|---|---|---|
| Pesticide residue | EWG Dirty Dozen / Clean Fifteen 2024, USDA sampling data | 45% |
| Microplastic exposure | Packaging type + food-specific absorption rate | 35% |
| Processing level | NOVA classification proxy | 20% |

It outputs a 0–10 concern score with a label (MINIMAL / LOW / MODERATE / HIGH), detailed breakdowns per category, an actionable verdict, and probable food origin by region.

All scans are stored locally in SQLite so you can track patterns over time.

---

## Install

```bash
git clone https://github.com/rishithangada/foodprint.git
cd foodprint
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

---

## Usage

**Interactive scan:**
```bash
python foodprint.py
```

```
FOODPRINT contamination scanner v1.0

Food name: strawberries
Store name: HEB
City: Austin
State: TX
Country: USA
Packaging type: plastic clamshell
Organic?: No

── Analyzing ──────────────────────────────────────
  ◆ pesticide_score    9.8  HIGH   [EWG Dirty Dozen 2024]
  ◆ microplastic_score 7.1  HIGH   [surface contact + static charge]
  ◆ processing_score   1.0  MINIMAL
  ◆ overall_score      7.0  MODERATE

  Verdict: Buy organic and wash under running water for 30+ seconds.
           Avoid microwaving in this packaging. High cumulative exposure
           risk with regular consumption.

  Origin: Central Mexico (Baja CA) · Florida (seasonal)
```

**View scan history:**
```bash
python foodprint.py history
```

**Stats across all scans:**
```bash
python foodprint.py stats
```

**Web dashboard:**
```bash
python web/server.py
# → open http://localhost:5050
```

---

## Data sources

- **EWG Dirty Dozen / Clean Fifteen 2024** — annual pesticide residue rankings from Environmental Working Group
- **USDA Pesticide Data Program** — residue detection rates across 10,000+ food samples
- **Nature Medicine (2024), Campen et al.** — microplastic concentrations in human brain tissue
- **Environmental Science & Technology** — microplastic transfer rates by packaging material
- **NOVA food classification** — processing level framework from University of São Paulo

---

## Project structure

```
foodprint/
├── foodprint.py        # CLI entry point
├── engine/
│   ├── scorer.py       # pesticide + microplastic + processing scoring
│   ├── display.py      # rich terminal output
│   ├── origin.py       # food origin detection by region
│   ├── database.py     # SQLite scan history
│   └── api.py          # USDA FoodData Central + Open Food Facts
├── web/
│   ├── server.py       # FastAPI/Flask web server
│   └── index.html      # cinematic dashboard
└── data/
    └── foodprint.db    # local scan history (gitignored)
```

---

## Why this exists

The 2024 Nature Medicine study found microplastics in human brain tissue at concentrations 30× higher than in the liver or kidney — and people with dementia had significantly higher levels. Meanwhile EWG testing found 22+ pesticide residues on a single strawberry sample.

Nobody is aggregating this into something you can actually use day-to-day. FoodPrint is that tool.

---

*Built by [@upwitrish](https://instagram.com/upwitrish)*
