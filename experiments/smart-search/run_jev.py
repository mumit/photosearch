"""Jev's answers to the labelled searches, for scoring only (never as training data: TypeSafe's terms)."""
import json, sys, time
from pathlib import Path
HERE = Path(__file__).parent
OUT = HERE.parent.parent / "data" / "eval" / "smart-search"  # model answers: git-ignored
sys.path.insert(0, str(HERE))
from queries import TUNE, TEST
from photosearch.smartbox import ask_jev, jev_key
assert jev_key(), "no Jev key"
out = {}
for q, *_ in TUNE + TEST:
    t = time.time(); a = ask_jev(q); out[q] = dict(answers=a, ms=(time.time() - t) * 1000)
OUT.mkdir(parents=True, exist_ok=True); json.dump(out, open(OUT / "raw-jev.json", "w"), indent=1)
print("jev", len(out), "median ms", round(sorted(v["ms"] for v in out.values())[len(out) // 2]))
