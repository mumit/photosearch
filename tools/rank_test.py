"""Does indexing at 70 vision tokens change which photos a search returns, compared with the index's 280-token vectors?

Re-embeds a random sample of an index built at 280 tokens, at 70 (reading the same local previews the index used), then
runs the same searches over the sample with both sets of vectors. The README's Measurements came from this, on a
17k-photo library:

    uv run python tools/rank_test.py

Only reads the index. Writes the numbers to rank-test.json in the data folder.
"""
import json, random, sqlite3, time
from pathlib import Path

import numpy as np

from photosearch import embed
from photosearch.config import DATA, DB
from photosearch.images import open_image

N, SPEED_N, BATCH = 2000, 200, 16
QUERIES = [
    "a beach at sunset", "snow-covered mountains", "a waterfall", "a dog playing", "a cat sleeping",
    "a birthday cake with candles", "a city skyline at night", "people hiking on a trail", "a plate of food",
    "a forest path", "a lake with reflections", "fireworks", "a car", "a bicycle", "flowers in a garden",
    "a museum", "a church interior", "a market stall", "a boat on the water", "a bridge", "a selfie",
    "a group photo", "a child on a swing", "a pool", "a sports game in a stadium", "a concert", "a screenshot",
    "a document or receipt", "a whiteboard", "a train", "an airplane window view", "a desert", "autumn leaves",
    "rain", "a campfire", "a Christmas tree", "a wedding", "a baby", "coffee", "a street at night",
    "a castle", "a farm with animals", "a playground", "a hotel room", "a kitchen", "ice cream",
    "the ocean with waves", "a view from the top of a mountain", "a picnic", "a cozy living room",
]


def encode(m, rows, tokens):
    proc = m[0].processor
    proc.image_seq_length = proc.image_processor.image_seq_length = tokens
    proc.image_processor.max_soft_tokens = tokens
    vecs, t_load, t_enc = [], 0.0, 0.0
    for i in range(0, len(rows), BATCH):
        t = time.time(); ims = [open_image(src) for _, src, _ in rows[i:i + BATCH]]; t_load += time.time() - t
        t = time.time()
        vecs.append(m.encode([{"image": im} for im in ims], batch_size=len(ims), normalize_embeddings=True).astype(np.float32))
        t_enc += time.time() - t
        print(f"\r  {tokens} tokens: {i + len(ims)}/{len(rows)}  {(i + len(ims)) / (t_load + t_enc):.1f}/s", end="", flush=True)
    print()
    return np.concatenate(vecs), t_load, t_enc


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    if dict(con.execute("select key, value from meta")).get("vision_tokens") != "280":
        raise SystemExit("this compares against an index built at 280 vision tokens")
    rows = [r for r in con.execute("select uuid, src, vec from photos") if r[1] and Path(r[1]).exists()]
    random.Random(7).shuffle(rows)
    rows = rows[:N]
    v280 = np.stack([np.frombuffer(r[2], np.float32) for r in rows])
    m = embed.model()
    m.encode([{"image": open_image(rows[0][1])}])  # warm up

    out = {}
    s280, l280, e280 = encode(m, rows[:SPEED_N], 280)
    s70, l70, e70 = encode(m, rows[:SPEED_N], 70)
    out["speed"] = dict(n=SPEED_N, load_s=round(l280 + l70, 1), encode_280_per_s=round(SPEED_N / e280, 2),
                        encode_70_per_s=round(SPEED_N / e70, 2), with_load_280_per_s=round(SPEED_N / (l280 + e280), 2),
                        with_load_70_per_s=round(SPEED_N / (l70 + e70), 2))
    out["sanity_280_vs_index_cos"] = round(float((s280 * v280[:SPEED_N]).sum(1).mean()), 4)

    rest, _, _ = encode(m, rows[SPEED_N:], 70)
    v70 = np.concatenate([s70, rest])
    cos = (v70 * v280).sum(1)
    out["cos_70_vs_280"] = dict(mean=round(float(cos.mean()), 4), p5=round(float(np.percentile(cos, 5)), 4),
                                min=round(float(cos.min()), 4))

    per = []
    for q in QUERIES:
        qv = embed.embed_query(q)
        a, b = v280 @ qv, v70 @ qv
        ra, rb = np.argsort(-a), np.argsort(-b)
        pos_b = np.empty(len(rows), int); pos_b[rb] = np.arange(len(rows))
        per.append(dict(q=q, top1_same=bool(ra[0] == rb[0]), top1_280_rank_in_70=int(pos_b[ra[0]]) + 1,
                        top1_in_top5=bool(ra[0] in rb[:5]), overlap10=len(set(ra[:10]) & set(rb[:10])),
                        overlap24=len(set(ra[:24]) & set(rb[:24])), gap_1_2_280=round(float(a[ra[0]] - a[ra[1]]), 4)))
    out["per_query"] = per
    n = len(per)
    out["summary"] = dict(queries=n, photos=len(rows),
                          top1_same=sum(p["top1_same"] for p in per),
                          top1_in_top5=sum(p["top1_in_top5"] for p in per),
                          mean_overlap10=round(sum(p["overlap10"] for p in per) / n, 2),
                          mean_overlap24=round(sum(p["overlap24"] for p in per) / n, 2))
    (DATA / "rank-test.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "per_query"}, indent=1))


main()
