"""Importing the API module must not write anything.

:func:`~moadian.api.app.create_app` reads .env, loads the signing key and seeds
accounts. While it ran at module scope, importing the module was enough to do
all three — so running the test suite inside a deployment checkout created an
``admin``/``admin1234`` account in the live database, and the real
MOADIAN_SEED_USERS was ignored from then on because seeding never overwrites an
existing user.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src"


def _run(code: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={
            "PYTHONPATH": str(SOURCE),
            "PATH": "/usr/bin:/bin",
            # Deliberately absent: MOADIAN_MASTER_PASSPHRASE and every other
            # setting. A bare import must not need them either.
        },
    )


def test_importing_the_module_creates_no_instance_directory(tmp_path: Path) -> None:
    """The regression, stated as the symptom that gave it away."""
    result = _run("import moadian.api.app", tmp_path)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == [], f"import wrote {list(tmp_path.iterdir())}"


def test_importing_create_app_by_name_is_still_inert(tmp_path: Path) -> None:
    """How every test and tool in this repo imports it."""
    result = _run("from moadian.api.app import create_app", tmp_path)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_the_app_attribute_still_resolves(tmp_path: Path) -> None:
    """What ``uvicorn moadian.api.app:app`` does, and it must keep working.

    Building it *does* seed, which is the point — so this one expects the
    instance directory to appear.
    """
    result = _run(
        "from moadian.api.app import app\n"
        "assert app.title == 'Moadian'\n"
        "print('built')",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "built" in result.stdout
    assert (tmp_path / "instance").is_dir()


def test_the_app_attribute_is_built_once(tmp_path: Path) -> None:
    result = _run(
        "import moadian.api.app as m\nassert m.app is m.app\nprint('same')", tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert "same" in result.stdout


def test_an_unknown_attribute_still_raises(tmp_path: Path) -> None:
    """A module __getattr__ that swallows everything hides typos forever."""
    result = _run(
        "import moadian.api.app as m\n"
        "try:\n"
        "    m.no_such_thing\n"
        "except AttributeError as exc:\n"
        "    print('raised', exc)\n"
        "else:\n"
        "    raise SystemExit('no AttributeError')",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "raised" in result.stdout
