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


def two_searches(tmp_path):
    f = tmp_path / "q.txt"; f.write_text("a beach at sunset\nsnow\n")
    return str(f)


def test_rules_for_ranking_are_compared_over_the_whole_library(tmp_path, con):
    r = run("rules", "search", a="search=nohub", queries=two_searches(tmp_path))
    assert r["whole"] and r["photos"] == con.execute("select count(*) from photos").fetchone()[0]
    assert r["summary"]["first_same"] == 2  # the made-up library has too few labels for the hub penalty
    assert "The whole library" in evals.report("rules")
    with pytest.raises(SystemExit, match="not with a sample"):
        run("mixed", "search", a="index")
    with pytest.raises(SystemExit, match="needs Jev"):  # no key in the tests
        run("nojev", "search=check", a="search", queries=two_searches(tmp_path))


def test_jevs_check_can_be_a_variant(tmp_path, monkeypatch):
    from photosearch import checks, smartbox
    monkeypatch.setattr(smartbox, "jev_key", lambda: "test-key")
    monkeypatch.setattr(checks, "ask", lambda q, ds: [1.0] * len(ds))
    r = run("jev", "search=check", a="search", queries=two_searches(tmp_path))
    assert len(r["searches"]) == 2 and all(len(p["B"]) == evals.TOP for p in r["searches"])


def test_a_sheet_is_blind_and_comes_in_order(tmp_path):
    run("blind", "dims=64", queries=two_searches(tmp_path))
    s = evals.sheet("blind", judge="Sam")
    assert s["n"] == 1 and s["left"] == 2 and len(s["x"]) == len(s["y"]) == 3 and s["verdict"] is None
    assert not {"A", "B", "a", "b"} & set(s)  # nothing says which row is which
    assert evals.record("blind", 1, "Sam", [1, 3], [], "x") == 1
    assert evals.sheet("blind", judge="Sam")["n"] == 2
    assert evals.sheet("blind", 1, judge="Sam")["verdict"] == dict(x=[1, 3], y=[], first="x")
    assert evals.sheet("blind", judge="Alex")["n"] == 1  # each judge has their own place
    evals.record("blind", 2, "Sam", [], [2], "same")
    assert evals.sheet("blind", judge="Sam")["done"]


def test_verdicts_are_checked(tmp_path):
    run("bad", "dims=64", queries=two_searches(tmp_path))
    for n, who, x, first in ((9, "Sam", [], "x"), (1, "Sam", [4], "x"), (1, "Sam", [], "z"), (1, " ", [], "x")):
        with pytest.raises(ValueError):
            evals.record("bad", n, who, x, [], first)
    for name in ("../bad", ".hidden", "nope"):
        with pytest.raises(LookupError):
            evals.sheet(name)


def test_results_wait_for_every_sheet_then_compare_judges(tmp_path):
    r = run("two", "dims=64", queries=two_searches(tmp_path))
    evals.record("two", 1, "Sam", [1, 2, 3], [1], "x")
    with pytest.raises(LookupError, match="judge every sheet"):
        evals.results("two", "Sam")
    evals.record("two", 2, "Sam", [], [], "same")
    evals.record("two", 1, "Alex", [1, 2], [1], "x")  # one photo called the other way
    res = evals.results("two", "Sam")
    a_fit = 3 if r["searches"][0]["x"] == "A" else 1
    assert res["judges"]["Sam"]["fit"] == {"A": a_fit, "B": 4 - a_fit} and res["judges"]["Alex"]["sheets"] == 1
    assert res["agree"]["Alex"] == dict(sheets=1, photos=6, same=5)
    assert "called 5 of 6 photos the same way (83%)" in evals.report("two")
