"""Tests for wheel argument validation."""

import zipfile

import pytest
from sample_data import ALL_WHEELS

from daleq4py.wheel import WheelValidationError, validate_wheel

VALID_WHEEL_NAME = "daleq4py-0.1.0-py3-none-any.whl"


def _make_wheel(directory, name=VALID_WHEEL_NAME):
    """Create a minimal but structurally valid .whl (a zip archive)."""
    path = directory / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("daleq4py/__init__.py", "")
    return path


def test_accepts_valid_wheel(tmp_path):
    wheel = _make_wheel(tmp_path)
    assert validate_wheel(str(wheel)) == wheel.resolve()


def test_rejects_missing_path(tmp_path):
    with pytest.raises(WheelValidationError, match="does not exist"):
        validate_wheel(str(tmp_path / "missing.whl"))


def test_rejects_directory(tmp_path):
    with pytest.raises(WheelValidationError, match="not a file"):
        validate_wheel(str(tmp_path))


def test_rejects_wrong_extension(tmp_path):
    other = tmp_path / "package.zip"
    other.write_bytes(b"")
    with pytest.raises(WheelValidationError, match="not a wheel"):
        validate_wheel(str(other))


def test_rejects_bad_filename(tmp_path):
    wheel = _make_wheel(tmp_path, name="not-a-real-wheel.whl")
    with pytest.raises(WheelValidationError, match="naming convention"):
        validate_wheel(str(wheel))


def test_rejects_non_zip(tmp_path):
    fake = tmp_path / VALID_WHEEL_NAME
    fake.write_bytes(b"not a zip archive")
    with pytest.raises(WheelValidationError, match="not a valid zip"):
        validate_wheel(str(fake))


@pytest.mark.parametrize("wheel", ALL_WHEELS, ids=lambda w: w.name)
def test_accepts_real_sample_wheels(wheel):
    """Every alternatively built sample wheel passes validation."""
    assert validate_wheel(str(wheel)) == wheel.resolve()
