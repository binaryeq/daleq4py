"""Shared pytest fixtures.

Concrete paths to the sample wheels live in ``tests/sample_data.py``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# EDB files produced by tests go here, under the project folder, so they are
# easy to inspect and never pollute the system temp directory.
EDB_TEST_DIR = ".souffle-test"


@pytest.fixture(scope="session", autouse=True)
def clear_edb_test_dir() -> None:
    """Wipe ``.souffle-test`` once before the whole test run (like @BeforeAll).

    ``autouse`` + ``scope="session"`` means this runs exactly once, before any
    test, whether or not a test asks for it. Output from the latest run is
    left behind afterwards so it can be inspected.
    """
    resolved = PROJECT_ROOT / EDB_TEST_DIR
    if resolved.exists():
        shutil.rmtree(resolved)


@pytest.fixture(scope="session")
def edb_base_dir() -> str:
    """Base directory for EDB files written by tests.

    Returns the relative form: ``extract_edb`` resolves it against the project
    root. The directory itself is cleared by :func:`clear_edb_test_dir`.
    """
    return EDB_TEST_DIR
