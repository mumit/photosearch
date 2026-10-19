"""The words in photos (signs, pages, receipts, shirts), read on this Mac by Apple's Vision framework, so a search
can find what the model only sees as shapes. Kept in this index, never in Photos."""
import re, time
from datetime import datetime
from pathlib import Path

from .config import THUMBS

MIN_CONF = 0.5  # Vision's confidence in a line; below it, most lines are a guess at a texture


def read(path):
    """The lines of text Vision finds in an image file, in reading order."""
    import Vision
    from Foundation import NSURL
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)  # 0.05 s a photo; the fast level misreads most
    h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(path)), None)
    ok, _ = h.performRequests_error_([req], None)
    lines = []
    for o in (req.results() or []) if ok else []:
        c = o.topCandidates_(1)
        if c and c[0].confidence() >= MIN_CONF:
            lines.append(str(c[0].string()))
    return lines


def read_all(con, limit=None):
    """Reads every photo not read yet, newest first: its local preview, else its thumbnail."""
    todo = con.execute("select uuid, src from photos where kind='photo' and uuid not in (select uuid from texts) "
                       "order by date desc").fetchall()
    todo = todo[:limit] if limit else todo
    print(f"text: {con.execute('select count(*) from texts').fetchone()[0]} read, {len(todo)} to go", flush=True)
    t0, n, found = time.time(), 0, 0
    for u, src in todo:
        f = src if src and Path(src).exists() else THUMBS / f"{u}.jpg"
        try:
            lines = read(f) if Path(f).exists() else []
        except Exception as ex:  # an image Vision can't open: leave it for next time
            print(f"\n  couldn't read {u}: {ex.__class__.__name__}"); continue
        con.execute("insert or replace into texts values(?,?,?)", (u, "\n".join(lines), datetime.now().isoformat()))
        n += 1; found += bool(lines)
        if n % 50 == 0 or n == len(todo):
            con.commit()
            rate = n / (time.time() - t0)
            print(f"\r{n}/{len(todo)}  {rate:.0f}/s  eta {(len(todo) - n) / rate / 60:.0f} min  with text {found}   ",
                  end="", flush=True)
    con.commit()
    if todo:
        print(f"\ntext: read {n} in {(time.time() - t0) / 60:.1f} min, {found} with words in them")


def cmd_text(a):
    from .store import db
    read_all(db(), a.limit)


def words(s):
    """Lowercase words, a plural folded into its singular."""
    out = []
    for w in re.findall(r"\w+", s.lower()):
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


_texts = (None, {})

def written(con):
    """{uuid: the set of words written in it}, reloaded when more photos are read."""
    global _texts
    stamp = con.execute("select count(*), max(rowid) from texts").fetchone()
    if _texts[0] != stamp:
        _texts = (stamp, {u: set(words(t)) for u, t in con.execute("select uuid, text from texts where text != ''")})
    return _texts[1]


def quoted(query):
    """(the phrases in quotes, the rest of the search)."""
    q = r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]'
    return [p.strip() for p in re.findall(q, query) if p.strip()], " ".join(re.sub(q, " ", query).split())


def written_in(con, phrases):
    """The photos with every word of the phrases written in them."""
    need = {w for p in phrases for w in words(p)}
    return {u for u, ws in written(con).items() if need <= ws} if need else set()
