"""`photosearch eval`: comparing two variants of the index, and unblinding what a judge scored."""
import json, shutil, sqlite3

import numpy as np
import pytest

from photosearch import config, evals


def run(name, b, **kw):
    evals.run(name, b, **dict(dict(n=500, k=3), **kw))
    return json.loads((evals.EVALS / name / "run.json").read_text())


def test_the_index_against_itself_agrees_completely():
    r = run("same", "index")
    s = r["summary"]
    assert s["first_same"] == s["searches"] == 50 and s["overlap10"] == 10 and s["cos"]["min"] > 0.999
    assert len(list((evals.EVALS / "same" / "sheets").glob("*.jpg"))) == 50


def test_the_same_seed_picks_the_same_photos(con):
    a, b = evals.sample(con, 20, 3), evals.sample(con, 20, 3)
    assert [r[0] for r in a] == [r[0] for r in b] != [r[0] for r in evals.sample(con, 20, 4)]


def test_shorter_vectors_still_find_the_beach():
    r = run("short", "dims=64")
    beach = next(p for p in r["searches"] if p["q"] == "a beach at sunset")
    assert beach["first_same"]  # the fake model's concepts live in the first numbers


def test_compressed_vectors_are_compared():
    for bits in ("1", "8"):
        r = run(f"bits{bits}", f"bits={bits}")
        assert 0 < r["summary"]["cos"]["mean"] < 1.0001


def test_another_vision_token_setting_embeds_the_sample_again(monkeypatch):
    seen = []

    def fake(paths, tokens):
        seen.append((len(paths), tokens))
        rng = np.random.default_rng(tokens)
        return evals.unit(rng.standard_normal((len(paths), config.DIM)).astype(np.float32)), 2.0

    monkeypatch.setattr(evals, "embed_images", fake)
    r = run("tokens", "tokens=70", n=40, speed=10)
    assert seen[0] == (40, 70) and (10, 280) in seen
    assert r["notes"]["tokens=70"]["photos_per_s"] == 20.0 and r["summary"]["first_same"] < 50


def test_another_index_must_have_the_whole_sample(tmp_path, con):
    other = tmp_path / "other"
    shutil.copytree(config.DATA, other)
    assert run("copy", f"index={other}")["summary"]["first_same"] == 50
    u = evals.sample(con, 500, 7)[0][0]
    o = sqlite3.connect(other / "index.sqlite"); o.execute("delete from photos where uuid=?", (u,)); o.commit()
    with pytest.raises(SystemExit, match="1 of the sample"):
        run("gap", f"index={other}")


def test_the_report_unblinds_the_judges_scores():
    r = run("judged", "dims=64")
    x1, x2 = r["searches"][0]["x"], r["searches"][1]["x"]
    evals.score("judged", 1, x="1,2,3", y="", first="x")
    evals.score("judged", 2, x="1", y="1,2", first="same", judge="claude")
    text = evals.report("judged")
    a_fit = 3 if x1 == "A" else 0
    assert f"| Top-3 photos that fit the search (of 3) | {a_fit} | {3 - a_fit} |" in text
    assert "Judged blind by claude: 1 of 50" in text
    claude_a = 1 if x2 == "A" else 2
    assert f"(of 3) | {claude_a} | {3 - claude_a} |" in text
    assert (evals.EVALS / "judged" / "report.md").read_text() == text


def test_a_judged_run_isnt_overwritten():
    run("once", "dims=64")
    evals.score("once", 1, x="1")
    with pytest.raises(SystemExit, match="judged already"):
        run("once", "dims=64")


def test_scores_are_checked():
    run("checked", "dims=64")
    for bad in (dict(n=99), dict(n=1, x="7"), dict(n=1, first="z")):
        with pytest.raises(SystemExit):
            evals.score("checked", **bad)
