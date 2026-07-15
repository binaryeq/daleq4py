# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Tests for IDB → markdown summary projection."""

import shutil
from pathlib import Path

import pytest
from sample_data import COLORLOG_PYPI

from daleq4py.extract_edb import extract_edb
from daleq4py.inference import run_inference
from daleq4py.project_idb import (
    RULES_DIR,
    SUMMARY_FILENAME,
    SUMMARY_REDUCED_FILENAME,
    _parse_decls,
    project_idb,
    main,
)

requires_souffle = pytest.mark.skipif(
    shutil.which("souffle") is None,
    reason="souffle executable not on PATH",
)


# --- input validation ---


def test_project_idb_rejects_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        project_idb(tmp_path / "nope")


def test_project_idb_rejects_empty_dir(tmp_path):
    empty = tmp_path / "idb"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="no .tsv"):
        project_idb(empty, include_only_predicates=None)


# --- .decl parsing (no souffle invocation needed) ---


def test_parse_decls_extracts_content_and_package_columns():
    decls = _parse_decls(RULES_DIR)
    assert decls["content"] == ["id", "file", "path", "key", "value"]
    assert decls["package"] == ["id", "key", "value"]


# --- end-to-end ---


@requires_souffle
def test_project_idb_writes_summary_in_session_dir(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)
    session_dir = idb_dir.parent

    summary = project_idb(idb_dir)

    assert summary == session_dir / SUMMARY_FILENAME
    assert summary.exists()


@requires_souffle
def test_project_idb_contains_predicate_sections_and_headers(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    text = project_idb(idb_dir).read_text(encoding="utf-8")

    # Both predicate sections are present, one header each.
    assert "## content" in text
    assert "## package" in text
    # Column headers are taken from the .decl in rules/core.souffle.
    assert "| id | file | path | key | value |" in text
    assert "| id | key | value |" in text


@requires_souffle
def test_project_idb_contains_no_remove_content_predicate_section_by_default(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    text = project_idb(idb_dir).read_text(encoding="utf-8")

    # Both predicate sections are present, one header each.
    assert "## remove_content" not in text


@requires_souffle
def test_project_idb_includes_sample_facts(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    text = project_idb(idb_dir).read_text(encoding="utf-8")
    # Package facts derived from colorlog's dist-info.
    assert "colorlog-6.7.0" in text
    assert "colorlog-6.7.0.dist-info" in text
    # R_METADATA / R_PACKAGE prefixes attached by the lift rules.
    assert "R_CONTENT[" in text
    assert "R_PACKAGE[" in text


@requires_souffle
def test_project_idb_table_row_count_matches_facts(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    package_facts = (idb_dir / "package.tsv").read_text(encoding="utf-8").splitlines()
    text = project_idb(idb_dir).read_text(encoding="utf-8")

    # All non-empty lines between "## package" and the next section / EOF.
    section = text.split("## package", 1)[1]
    # Two header rows (column names + separator) plus one row per fact.
    assert section.count("\n|") == 2 + len(package_facts)


# --- remove_derivation flag ---


@requires_souffle
def test_project_idb_default_keeps_id_column(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    summary = project_idb(idb_dir, remove_derivation=False)

    assert summary.name == SUMMARY_FILENAME
    text = summary.read_text(encoding="utf-8")
    assert "| id | file | path | key | value |" in text
    assert "R_CONTENT[" in text


@requires_souffle
def test_project_idb_remove_derivation_uses_reduced_filename(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    summary = project_idb(idb_dir, remove_derivation=True)

    assert summary.name == SUMMARY_REDUCED_FILENAME
    assert summary == idb_dir.parent / SUMMARY_REDUCED_FILENAME
    assert summary.exists()


@requires_souffle
def test_project_idb_remove_derivation_drops_id_column(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    text = project_idb(idb_dir, remove_derivation=True).read_text(encoding="utf-8")

    # Header rows no longer carry the id column.
    assert "| file | path | key | value |" in text
    assert "| key | value |" in text
    # Neither the original ``id`` header nor any R_CONTENT/R_PACKAGE entry remains.
    assert "| id | " not in text
    assert "R_CONTENT[" not in text
    assert "R_PACKAGE[" not in text
    # Actual facts are still rendered.
    assert "colorlog-6.7.0" in text


@requires_souffle
def test_project_idb_both_modes_produce_separate_files(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    full = project_idb(idb_dir)
    reduced = project_idb(idb_dir, remove_derivation=True)

    assert full != reduced
    assert full.exists() and reduced.exists()


@requires_souffle
def test_project_idb_includes_all_predicates_in_sorted_order_when_specified(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    text = project_idb(idb_dir, remove_derivation=True, include_only_predicates=None).read_text(encoding="utf-8")

    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## content", "## package", "## remove_content"]


@requires_souffle
def test_project_idb_includes_specified_predicates_in_given_order_when_specified(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    text = project_idb(idb_dir, remove_derivation=True, include_only_predicates=["remove_content", "package"]).read_text(encoding="utf-8")

    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## remove_content", "## package"]


# Simple "integration tests" to check command line handling

def _check_headings(idb_dir: Path, headings_expected: list[str]) -> None:
    summary_path = idb_dir.parent / "normalisation-summary.md"
    text = summary_path.read_text(encoding="utf-8")
    headings_present = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings_present == headings_expected


@requires_souffle
def test_main_includes_content_then_package_predicates_by_default(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    main([str(idb_dir)])
    _check_headings(idb_dir, ["## content", "## package"])


@requires_souffle
def test_main_includes_all_predicates_in_sorted_order_when_specified(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    main(["--include-all-predicates", str(idb_dir)])
    _check_headings(idb_dir, ["## content", "## package", "## remove_content"])


@requires_souffle
def test_main_includes_specified_predicates_in_given_order_when_specified(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    idb_dir = run_inference(content_path.parent)

    main(["--include-only-predicates", "remove_content,package", str(idb_dir)])
    _check_headings(idb_dir, ["## remove_content", "## package"])
