"""Shared pytest fixtures.

Test wheels live under ``tests/data/<package>/<version>/<builder>/`` where
``builder`` is one of ``pypi``, ``macaron`` or ``ossr`` — each an alternatively
built wheel for the same package, version pair, intended to be compared.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent / "data"

BUILDERS = ("pypi", "macaron", "ossr")


def _sample_packages() -> list[tuple[str, str]]:
    """Discover ``(package, version)`` pairs available under ``tests/data``."""
    pairs = []
    for package_dir in sorted(DATA_DIR.iterdir()):
        if not package_dir.is_dir():
            continue
        for version_dir in sorted(package_dir.iterdir()):
            if version_dir.is_dir():
                pairs.append((package_dir.name, version_dir.name))
    return pairs


@pytest.fixture
def data_dir() -> Path:
    """Root directory holding the sample wheels."""
    return DATA_DIR


@pytest.fixture(params=_sample_packages(), ids=lambda p: f"{p[0]}-{p[1]}")
def sample_wheels(request) -> dict[str, Path]:
    """Map each builder name to its wheel for one sample ``(package, version)``.

    Parametrised: a test using this fixture runs once per sample package.
    """
    package, version = request.param
    wheels = {}
    for builder in BUILDERS:
        builder_dir = DATA_DIR / package / version / builder
        matches = list(builder_dir.glob("*.whl"))
        assert len(matches) == 1, f"expected one wheel in {builder_dir}"
        wheels[builder] = matches[0]
    return wheels
