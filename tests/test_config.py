"""Where your data lives: next to the code in a checkout, in Application Support once installed, so an upgrade
(which replaces the installed package's folder) never takes the index with it."""
import importlib.util, shutil
from pathlib import Path

from photosearch import config


def load(config_py, monkeypatch, data=None):
    """config.py as if it lived at config_py, with PHOTOSEARCH_DATA set to data (or unset)."""
    if data: monkeypatch.setenv("PHOTOSEARCH_DATA", str(data))
    else: monkeypatch.delenv("PHOTOSEARCH_DATA")
    spec = importlib.util.spec_from_file_location("config_copy", config_py)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def installed(tmp_path):
    """A copy of config.py where pip or uv tool puts it: site-packages, with no pyproject.toml two folders up."""
    pkg = tmp_path / "lib" / "python3.12" / "site-packages" / "photosearch"
    pkg.mkdir(parents=True)
    return Path(shutil.copy(config.__file__, pkg))


def test_a_checkout_keeps_data_at_its_top(monkeypatch):
    m = load(config.__file__, monkeypatch)
    assert m.ROOT == m.CHECKOUT and (m.ROOT / "pyproject.toml").exists()
    assert m.DATA == m.CHECKOUT / "data"


def test_installed_keeps_data_in_application_support(tmp_path, monkeypatch):
    m = load(installed(tmp_path), monkeypatch)
    assert m.ROOT == Path.home() / "Library" / "Application Support" / "photosearch"
    assert m.DATA == m.ROOT / "data" and tmp_path not in m.DATA.parents


def test_photosearch_data_still_wins(tmp_path, monkeypatch):
    assert load(installed(tmp_path), monkeypatch, data=tmp_path / "demo").DATA == tmp_path / "demo"
