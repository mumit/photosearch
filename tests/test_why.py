"""Why a photo matches: where in it, which words, and what the model sees."""
from argparse import Namespace

import numpy as np
import pytest
from PIL import Image

from photosearch import why
from library import axis, noise, unit

W, H = 6, 4


@pytest.fixture
def squares(monkeypatch):
    """The fake model's squares: everyday stuff, with a dog in the top left corner unless spread=True."""
    rng = np.random.default_rng(3)
    state = dict(spread=False)
    def tokens(im):
        T = np.stack([unit(noise(rng, 1)) for _ in range(W * H)])
        dog = range(W * H) if state["spread"] else [0, 1, W, W + 1]
        for i in dog:
            T[i] = unit(axis("dog") + 0.3 * T[i])
        return T, W, H
    monkeypatch.setattr(why, "tokens", tokens)
    monkeypatch.setattr(why, "COMMON", 0)  # the made-up library has too few labels to leave out the common ones
    return state


def test_the_dog_is_lit_where_it_is(con, lib, squares):
    r = why.explain(con, "a dog", lib["dog0"])
    h = np.array(r["heat"])
    assert h.shape == (H, W) and h[:2, :2].min() > h[2:, 2:].max() and h.max() == 1
    assert not r["whole"] and r["score"] > 0.5
    squares["spread"] = True
    assert why.explain(con, "a dog", lib["dog0"])["whole"]  # the whole photo matches, not one part


def test_a_word_the_photo_does_not_fit_counts_against_it(con, lib, squares):
    words = {w["word"]: w for w in why.explain(con, "a dog on the beach", lib["dog0"])["words"]}
    assert set(words) == {"dog", "beach"}  # "a", "on", "the" aren't scored
    assert words["dog"]["change"] > 0 > words["beach"]["change"]
    assert words["beach"]["misfit"] and not words["dog"]["misfit"]


def test_it_sees_photos_own_words_and_embeds_them_once(con, lib, squares, monkeypatch):
    assert why.explain(con, "a dog", lib["dog0"])["sees"][0] == "Dog"
    monkeypatch.setattr(why.embed, "embed_query", lambda t: pytest.fail(f"embedded {t!r} again"))
    assert why.sees(con, np.asarray(axis("beach")))[0] == "Beach"


def test_the_command_writes_a_lit_copy(con, lib, squares, tmp_path, capsys):
    out = tmp_path / "why.jpg"
    why.cmd_why(Namespace(query="a dog", uuid=lib["dog0"][:8], out=str(out)))
    said = capsys.readouterr().out
    assert "score" in said and "sees: Dog" in said
    assert Image.open(out).size == why.source(con, lib["dog0"]).size
    with pytest.raises(LookupError):
        why.cmd_why(Namespace(query="a dog", uuid="", out=str(out)))  # every photo starts with ""


def test_the_page_asks_why(con, lib, squares):
    from server import Server
    srv = Server()
    try:
        r = srv.json(f"/api/why?q=a+dog&uuid={lib['dog0']}")
        assert r["sees"][0] == "Dog" and len(r["heat"]) == H and [w["word"] for w in r["words"]] == ["dog"]
        assert srv.get(f"/api/why?q=&uuid={lib['dog0']}")[0] == 404
    finally:
        srv.close()
