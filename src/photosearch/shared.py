"""Files more than one photosearch process writes: `serve`, `photosearch-mcp` and the commands all run at once on one
data folder. A file is written whole (a reader never sees half of one), and a change that reads a file and writes it
back holds a lock, so two writers can't drop each other's changes. The same locks keep two processes from driving
Photos at once, which can stall it."""
import fcntl, json, os, tempfile
from contextlib import contextmanager
from pathlib import Path

from . import config


@contextmanager
def held(name):
    """A lock on `name` across every photosearch process (and thread) using this data folder; waits for it."""
    config.DATA.mkdir(parents=True, exist_ok=True)
    with open(config.DATA / f".{name}.lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def write_json(path, obj, **dumps):
    """Write obj to path whole: into a temporary file beside it, then renamed over it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, **dumps)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextmanager
def updating(path, default=dict):
    """Read a JSON file (default() if there's none), let the caller change it, and write it back, all under one lock."""
    path = Path(path)
    with held(path.stem):
        obj = json.loads(path.read_text()) if path.exists() else default()
        yield obj
        write_json(path, obj)
