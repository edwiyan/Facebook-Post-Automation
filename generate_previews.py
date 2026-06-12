"""
Renders one sample image per day into ./image_improvements/ for visual review.
No posting to Facebook — purely local.
Run: python generate_previews.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_post import render

SAMPLES = {
    "Monday":    "New week, fresh energy — let the good vibes lead.",
    "Tuesday":   "STAY FREE",
    "Wednesday": "Flow like the tide today.",
    "Thursday":  "Be still. Be grateful.",
    "Friday":    "One love. Feel it.",
    "Saturday":  "Let the morning in.",
    "Sunday":    "Rest easy — tomorrow comes fresh.",
}

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "image_improvements")
os.makedirs(OUT_DIR, exist_ok=True)

for day, quote in SAMPLES.items():
    out = os.path.join(OUT_DIR, f"{day}.jpg")
    print(f"Rendering {day}: {quote!r}")
    render(day, quote, out)
    print(f"  Saved -> {out}")

print(f"\nAll previews saved to: {OUT_DIR}")
