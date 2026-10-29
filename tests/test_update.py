"""`photosearch update`, without reaching PyPI or running an installer: both are stand-ins here."""
from types import SimpleNamespace

import pytest

from photosearch import update


@pytest.fixture
def installed(monkeypatch):
    """As if installed with uv tool, at 0.1.0, with PyPI's newest set by the test; the upgrades it would run."""
    ran = []
    monkeypatch.setattr(update, "ROOT", update.CHECKOUT.parent / "Application Support")
    monkeypatch.setattr(update, "version", lambda: "0.1.0")
    monkeypatch.setattr(update, "upgrade_command", lambda: ["uv", "tool", "upgrade", "photosearch"])
    monkeypatch.setattr(update.subprocess, "run", lambda cmd: ran.append(cmd) or SimpleNamespace(returncode=0))
    return lambda newest: monkeypatch.setattr(update, "latest", lambda: newest) or ran


def test_a_checkout_says_to_git_pull(monkeypatch):
    monkeypatch.setattr(update, "latest", lambda: pytest.fail("a checkout shouldn't ask PyPI"))
    with pytest.raises(SystemExit, match="git pull"):
        update.cmd_update(SimpleNamespace(check=False))


def test_upgrades_when_theres_a_newer_one(installed, capsys):
    ran = installed("0.2.0")
    update.cmd_update(SimpleNamespace(check=False))
    assert ran == [["uv", "tool", "upgrade", "photosearch"]]
    assert "0.1.0 → 0.2.0" in capsys.readouterr().out


def test_check_only_says(installed, capsys):
    ran = installed("0.2.0")
    update.cmd_update(SimpleNamespace(check=True))
    assert ran == [] and "0.1.0 → 0.2.0" in capsys.readouterr().out


@pytest.mark.parametrize("newest", ["0.1.0", "0.1.0rc1"])
def test_nothing_to_do_when_newest(installed, capsys, newest):
    ran = installed(newest)
    update.cmd_update(SimpleNamespace(check=False))
    assert ran == [] and "is the newest" in capsys.readouterr().out


def test_not_on_pypi(installed):
    installed(None)
    with pytest.raises(SystemExit, match="isn't on PyPI"):
        update.cmd_update(SimpleNamespace(check=False))


def test_offline(installed, monkeypatch):
    installed("0.2.0")
    monkeypatch.setattr(update, "latest", lambda: (_ for _ in ()).throw(OSError("no network")))
    with pytest.raises(SystemExit, match="couldn't reach PyPI"):
        update.cmd_update(SimpleNamespace(check=False))


def test_upgrade_command_follows_the_installer():
    assert update.upgrade_command("/Users/me/.local/share/uv/tools/photosearch")[:3] == ["uv", "tool", "upgrade"]
    assert update.upgrade_command("/Users/me/.local/pipx/venvs/photosearch")[:2] == ["pipx", "upgrade"]
    assert update.upgrade_command("/Users/me/venv")[-3:] == ["install", "--upgrade", "photosearch"]
