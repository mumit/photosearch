"""Laya's answers to the labelled searches. Needs `pip install laya` (0.5.2 here), kept out of photosearch's
dependencies: run it from its own environment."""
import json, sys, time
from pathlib import Path
HERE = Path(__file__).parent
OUT = HERE.parent.parent / "data" / "eval" / "smart-search"  # model answers: git-ignored
sys.path.insert(0, str(HERE))
from queries import FRESH, TUNE, TEST
import ast, pathlib
src = (HERE.parent.parent / "src/photosearch/smartbox.py").read_text()
QUESTIONS = ast.literal_eval(src.split("JEV_QUESTIONS = ", 1)[1].split("\n\n\n", 1)[0])  # the same questions Jev gets
import laya
name = sys.argv[1]  # classic (the ModernBERT encoder) or vega (the default since 0.5)
t = time.time()
agent = laya.load("convaiinnovations/laya", device="mps") if name == "classic" else laya.load(vegaml=True, device="mps")
print(name, "loaded in", round(time.time() - t, 1), "s", type(agent).__name__, flush=True)
agent.predict(TUNE[0][0], QUESTIONS)  # warm up
out = {}
for q, *_ in TUNE + TEST + FRESH:
    t = time.time(); r = agent.predict(q, QUESTIONS)
    out[q] = dict(answers=r["answers"], ms=(time.time() - t) * 1000)
OUT.mkdir(parents=True, exist_ok=True); json.dump(out, open(OUT / f"raw-laya-{name}.json", "w"), indent=1, default=str)
print(name, len(out), "median ms", round(sorted(v["ms"] for v in out.values())[len(out) // 2]))
print(json.dumps(out[TUNE[0][0]]["answers"], default=str)[:600])
