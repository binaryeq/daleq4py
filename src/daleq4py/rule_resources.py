"""Locate bundled Soufflé rules independently of the repository layout."""

from importlib.resources import files
from importlib.resources.abc import Traversable


RULES_DIR = files("daleq4py").joinpath("rules")


def list_rule_files(rules_dir: Traversable) -> list[Traversable]:
    """Return rule resources in deterministic filename order."""
    if not rules_dir.is_dir():
        return []
    return sorted(
        (
            entry for entry in rules_dir.iterdir()
            if entry.is_file() and entry.name.endswith(".souffle")
        ),
        key=lambda entry: entry.name,
    )
