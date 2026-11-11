"""The words in photos (signs, pages, receipts, shirts), read on this Mac by Apple's Vision framework, so a search
can find what the model only sees as shapes. Kept in this index, never in Photos."""
import json, os, re, selectors, subprocess, sys, time
from datetime import datetime
from pathlib import Path

from .config import THUMBS

MIN_CONF = 0.5  # Vision's confidence in a line; below it, most lines are a guess at a texture
READER = [sys.executable, "-m", "photosearch", "read-text"]
BATCH = 200  # photos per reading process
WAIT = 30  # seconds for one photo before the reader is taken to be stuck (it takes ~0.05 s)
STUCK = 3  # stuck readers in a row before giving up for this run


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


def readings(jobs):
    """Yields (uuid, lines, or None if it wasn't read) for each (uuid, image file), read by `photosearch read-text`
    processes. Vision once stopped answering mid-run (inside Apple's text recognizer, where even ^C can't reach),
    so a photo that takes over WAIT seconds stops its reader, is left for next time, and a new reader goes on with the
    rest. Raises TimeoutError after STUCK stuck readers in a row: Vision isn't answering anyone."""
    queue, stuck = list(jobs), 0
    while queue:
        batch, queue = queue[:BATCH], queue[BATCH:]
        proc = subprocess.Popen([*READER, *(str(f) for _, f in batch)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        sel, buf, done = selectors.DefaultSelector(), b"", 0
        sel.register(proc.stdout, selectors.EVENT_READ)
        try:
            while done < len(batch):
                while b"\n" not in buf:
                    if not sel.select(WAIT) or not (chunk := os.read(proc.stdout.fileno(), 1 << 16)):
                        break  # stuck, or it stopped
                    buf += chunk
                if b"\n" not in buf:
                    break
                line, buf = buf.split(b"\n", 1)
                yield batch[done][0], json.loads(line)
                done, stuck = done + 1, 0
        finally:
            proc.kill(); proc.wait(); sel.close()
        if done < len(batch):
            yield batch[done][0], None
            if (stuck := stuck + 1) >= STUCK:
                raise TimeoutError
            queue = batch[done + 1:] + queue


def read_all(con, limit=None):
    """Reads every photo not read yet, newest first: its local preview, else its thumbnail."""
    todo = con.execute("select uuid, src from photos where kind='photo' and uuid not in (select uuid from texts) "
                       "order by date desc").fetchall()
    todo = todo[:limit] if limit else todo
    print(f"text: {con.execute('select count(*) from texts').fetchone()[0]} read, {len(todo)} to go", flush=True)
    t0, n, found = time.time(), 0, 0
    jobs = [(u, src if src and Path(src).exists() else THUMBS / f"{u}.jpg") for u, src in todo]
    gone = [u for u, f in jobs if not Path(f).exists()]  # nothing to read: no words
    con.executemany("insert or replace into texts values(?,'',?)", [(u, datetime.now().isoformat()) for u in gone])
    n, jobs = len(gone), [(u, f) for u, f in jobs if Path(f).exists()]
    try:
        for u, lines in readings(jobs):
            if lines is None:  # Vision couldn't open it, or got stuck on it: next time
                print(f"\n  couldn't read {u}; it's tried again next time"); continue
            con.execute("insert or replace into texts values(?,?,?)", (u, "\n".join(lines), datetime.now().isoformat()))
            n += 1; found += bool(lines)
            if n % 50 == 0 or n == len(todo):
                con.commit()
                rate = n / (time.time() - t0)
                print(f"\r{n}/{len(todo)}  {rate:.0f}/s  eta {(len(todo) - n) / rate / 60:.0f} min  with text {found}   ",
                      end="", flush=True)
    except TimeoutError:
        print(f"\ntext: Apple's Vision stopped answering; `photosearch text` reads the other {len(todo) - n} later")
    con.commit()
    if todo:
        print(f"\ntext: read {n} in {(time.time() - t0) / 60:.1f} min, {found} with words in them")


def cmd_read_text(a):
    """For `readings`: each image's lines as a JSON list, one line per image, in order (null if Vision couldn't)."""
    for f in a.files:
        try:
            lines = read(f)
        except Exception:
            lines = None
        print(json.dumps(lines), flush=True)


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
