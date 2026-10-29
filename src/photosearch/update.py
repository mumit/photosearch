"""`photosearch update`: the newest release from PyPI, for an installed copy (uv tool, pipx or pip). A git checkout
updates with `git pull` instead. Nothing checks for updates by itself: only this command reaches PyPI."""
import importlib.util, json, shutil, subprocess, sys, urllib.error, urllib.request
from importlib.metadata import PackageNotFoundError, version as installed_version

from packaging.version import Version

from .config import CHECKOUT, ROOT

PYPI = "https://pypi.org/pypi/photosearch/json"


def version():
    try:
        return installed_version("photosearch")
    except PackageNotFoundError:
        return "unknown"


def latest():
    """The newest version on PyPI, or None if photosearch isn't there."""
    try:
        with urllib.request.urlopen(PYPI, timeout=10) as r:
            return json.load(r)["info"]["version"]
    except urllib.error.HTTPError as ex:
        if ex.code == 404:
            return None
        raise


def upgrade_command(prefix=sys.prefix, has_pip=None):
    """How to upgrade, from how it was installed: each installer keeps its tools in a folder of its own. A venv that
    uv made has no pip, so uv installs into it instead."""
    if "/uv/tools/" in prefix:
        return ["uv", "tool", "upgrade", "photosearch"]
    if "/pipx/venvs/" in prefix:
        return ["pipx", "upgrade", "photosearch"]
    if has_pip is None:
        has_pip = importlib.util.find_spec("pip") is not None
    if not has_pip and shutil.which("uv"):
        return ["uv", "pip", "install", "--python", sys.executable, "--upgrade", "photosearch"]
    return [sys.executable, "-m", "pip", "install", "--upgrade", "photosearch"]


def cmd_update(a):
    if ROOT == CHECKOUT:
        sys.exit(f"{CHECKOUT} is a git checkout: update it with `git pull` and `uv sync`")
    now = version()
    try:
        new = latest()
    except OSError as ex:
        sys.exit(f"couldn't reach PyPI: {ex}")
    if new is None:
        sys.exit("photosearch isn't on PyPI")
    if now != "unknown" and Version(new) <= Version(now):
        print(f"photosearch {now} is the newest")
        return
    print(f"photosearch {now} → {new}")
    if a.check:
        return
    cmd = upgrade_command()
    print("running:", " ".join(cmd))
    if subprocess.run(cmd).returncode:
        sys.exit("the upgrade failed (see above)")
    print("Restart `photosearch serve`, and Claude Code if it uses photosearch, to run the new version.")
