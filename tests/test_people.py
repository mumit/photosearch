"""People's portraits: the one picked for them, the one I choose, and a crop around their face."""
import io, json
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from photosearch import index, people


def cover(con, name):
    return next(p["cover"] for p in people.people(con) if p["name"] == name)


def test_a_chosen_portrait_is_used_everywhere(lib, con):
    auto = cover(con, "Sam")
    pick = next(lib[k] for k in ("beach0", "lisbon0", "cake0") if lib[k] != auto)
    people.choose(con, "Sam", pick)
    assert cover(con, "Sam") == pick and people.person(con, "Sam")["portrait"] == pick
    people.choose(con, "Sam", None)
    assert cover(con, "Sam") == auto


def test_only_a_photo_they_are_tagged_in(lib, con):
    with pytest.raises(ValueError, match="isn't tagged"):
        people.choose(con, "Sam", lib["dog0"])
    with pytest.raises(LookupError):
        people.choose(con, "Sam", "NOT-A-PHOTO")
    people.choose(con, "Sam", lib["cake0"])
    con.execute("update photos set persons='[]' where uuid=?", (lib["cake0"],)); con.commit()
    assert cover(con, "Sam") != lib["cake0"]  # untagged in Photos since: back to the one picked for them


def test_the_crop_is_around_their_face(lib, con):
    u = lib["lisbon2"]
    assert people.face(con, u, "Sam") is None  # Photos hasn't said where their face is
    con.execute("update photos set faces=? where uuid=?", (json.dumps({"Sam": [0.9, 0.1, 0.05]}), u)); con.commit()
    im = Image.open(io.BytesIO(people.face(con, u, "Sam")))
    assert im.size == (people.FACE_PX, people.FACE_PX)
    assert len(list(people.FACES.glob(f"{u}-*.jpg"))) == 1  # made once, then kept
    assert people.face(con, u, "Alex") is None


def test_face_positions_count_from_the_top():
    p = NS(orientation=6, face_info=[NS(name="Sam", center_x=0.2, center_y=0.3, size=0.1),
                                     NS(name="_UNKNOWN_", center_x=0, center_y=0, size=0.2),
                                     NS(name="Sam", center_x=0.5, center_y=0.5, size=0.01)])  # the bigger face wins
    assert index.faces(p) == {"Sam": [0.2, 0.7, 0.1]}
    assert index.faces(NS(orientation=1)) == {}  # no face info at all
