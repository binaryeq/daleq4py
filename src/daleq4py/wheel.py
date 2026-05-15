"""Validation of Python wheel arguments.

Kept separate from the CLI layer so the rules can be unit tested directly.
A wheel is a zip archive whose name follows
``{distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl``
(see https://packaging.python.org/specifications/binary-distribution-format/).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

WHEEL_SUFFIX = ".whl"

# Minimum number of "-" separated components in a wheel filename (stem):
# distribution, version, python tag, abi tag, platform tag.
_MIN_WHEEL_NAME_PARTS = 5


class WheelValidationError(ValueError):
    """Raised when an argument is not a usable Python wheel."""


def validate_wheel(raw_path: str) -> Path:
    """Validate that ``raw_path`` points to a readable Python wheel.

    Returns the resolved :class:`~pathlib.Path` on success; raises
    :class:`WheelValidationError` with a human-readable message otherwise.
    """
    path = Path(raw_path).expanduser()

    if not path.exists():
        raise WheelValidationError(f"path does not exist: {raw_path}")
    if not path.is_file():
        raise WheelValidationError(f"not a file: {raw_path}")
    if path.suffix.lower() != WHEEL_SUFFIX:
        raise WheelValidationError(
            f"not a wheel (expected a '{WHEEL_SUFFIX}' file): {raw_path}"
        )

    parts = path.stem.split("-")
    if len(parts) < _MIN_WHEEL_NAME_PARTS or any(not p for p in parts):
        raise WheelValidationError(
            f"filename does not follow the wheel naming convention: {path.name}"
        )

    if not zipfile.is_zipfile(path):
        raise WheelValidationError(
            f"wheel is not a valid zip archive: {raw_path}"
        )

    return path.resolve()
