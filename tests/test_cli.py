"""Smoke tests for the CLI argument handling."""

import zipfile

import pytest

from daleq4py.cli import main

VALID_WHEEL_NAME = "daleq4py-0.1.0-py3-none-any.whl"


def _make_wheel(directory, name=VALID_WHEEL_NAME):
    path = directory / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("daleq4py/__init__.py", "")
    return path



def test_cli_compares_real_sample_wheels(sample_wheels):
    """The CLI accepts alternatively built wheels for the same package."""
    assert main([str(sample_wheels["pypi"]), str(sample_wheels["macaron"])]) == 0


def test_cli_requires_two_arguments(tmp_path):
    wheel = _make_wheel(tmp_path)
    with pytest.raises(SystemExit):
        main([str(wheel)])


def test_cli_rejects_invalid_wheel(tmp_path, capsys):
    wheel = _make_wheel(tmp_path)
    bad = tmp_path / "missing.whl"
    with pytest.raises(SystemExit):
        main([str(wheel), str(bad)])
    assert "does not exist" in capsys.readouterr().err
