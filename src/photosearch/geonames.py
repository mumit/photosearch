"""Place names for GPS positions, on this Mac, for folders of photos (Photos names its own): a town or city of 1,000
people or more from GeoNames' list (CC BY 4.0, geonames.org), with its state or province and country, as "Banff,
Alberta, Canada". The town is the most populous of those about as near as the nearest (TOWN_SLACK): the nearest
alone is often a village or suburb beside the town Photos would name (FINDINGS.md, Folders of photos). The list (11 MB) is downloaded once, the first time a folder's photos have GPS, into
~/.cache/photosearch/geonames; nothing about a photo is sent anywhere."""
import io, json, urllib.request, zipfile
from pathlib import Path

import numpy as np

CACHE = Path.home() / ".cache" / "photosearch" / "geonames"
URL = "https://download.geonames.org/export/dump/"
FAR_KM = 30  # farther than this from any town: just the state and country
TOWN_SLACK = (3, 2)  # the most populous town within 3 times the nearest one's distance, plus 2 km
# neighbourhoods (PPLX), and places that were (historical, abandoned, destroyed): Photos names the town itself
SKIP = {"PPLX", "PPLH", "PPLQ", "PPLW", "PPLCH"}
_places = None


def download():
    """The cities, states and countries from GeoNames, into CACHE as places.json and an array of positions."""
    CACHE.mkdir(parents=True, exist_ok=True)
    get = lambda name: urllib.request.urlopen(URL + name, timeout=60).read()
    countries = {r[0]: r[4] for r in (line.split("\t") for line in get("countryInfo.txt").decode().splitlines())
                 if r and not r[0].startswith("#") and len(r) > 4}
    states = {r[0]: r[1] for r in (line.split("\t") for line in get("admin1CodesASCII.txt").decode().splitlines()) if len(r) > 1}
    rows = []
    with zipfile.ZipFile(io.BytesIO(get("cities1000.zip"))) as z:
        for line in z.read("cities1000.txt").decode().splitlines():
            r = line.split("\t")
            if r[7] not in SKIP:
                rows.append((r[1], float(r[4]), float(r[5]), states.get(f"{r[8]}.{r[10]}", ""), countries.get(r[8], r[8]),
                             int(r[14] or 0)))
    save(rows)


def save(rows):
    """rows: (name, lat, lon, state, country, population), as the list to look places up in."""
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "places.json").write_text(json.dumps([(n, s, c, pop) for n, _, _, s, c, pop in rows], ensure_ascii=False))
    np.save(CACHE / "where.npy", unit(np.array([r[1:3] for r in rows], np.float64)))


def unit(latlon):
    """Points on the unit sphere, so the nearest by straight line is the nearest on the ground."""
    la, lo = np.radians(latlon[:, 0]), np.radians(latlon[:, 1])
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], 1)


def places():
    """(names, KD-tree of positions), downloading the list the first time; None if it can't be had (offline)."""
    global _places
    if _places is None:
        from scipy.spatial import cKDTree
        try:
            if not (CACHE / "where.npy").exists():
                print("naming places: downloading GeoNames' list of towns and cities (11 MB, once)…", flush=True)
                download()
            _places = (json.loads((CACHE / "places.json").read_text()), cKDTree(np.load(CACHE / "where.npy")))
        except (OSError, ValueError) as ex:
            print(f"naming places: couldn't get GeoNames' list ({ex.__class__.__name__}: {ex}); places stay unnamed for now")
            _places = False
    return _places or None


def name(points):
    """For each (lat, lon): dict(city, state, country, name), or None without the list. The city is left out when
    the nearest town is more than FAR_KM away (out at sea, say)."""
    got = places()
    if not got or not points:
        return [None] * len(points)
    names, tree = got
    times, km = TOWN_SLACK
    out = []
    for ds, ks in zip(*tree.query(unit(np.array(points, np.float64)), k=12)):
        ds = ds * 6371  # a chord this short is the distance on the ground
        k = max((k for d, k in zip(ds, ks) if d <= ds[0] * times + km), key=lambda k: names[k][3])
        city, state, country, _ = names[k]
        city = city if ds[0] <= FAR_KM else ""
        parts = [city, "" if state == city else state, country]  # "Mexico City, Mexico", not "Mexico City, Mexico City, …"
        out.append(dict(city=city, state=state, country=country, name=", ".join(x for x in parts if x)))
    return out
