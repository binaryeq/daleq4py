# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Tests for souffle inference on extracted EDBs."""

import shutil

import pytest
from sample_data import COLORLOG_PYPI

from daleq4py.extract_edb import EDB_FILENAME, PACKAGE_EDB_FILENAME, extract_edb
from daleq4py.inference import (
    MERGED_FILENAME,
    InferenceError,
    run_inference,
)


requires_souffle = pytest.mark.skipif(
    shutil.which("souffle") is None,
    reason="souffle executable not on PATH",
)


def _read_rows(tsv_path):
    text = tsv_path.read_text(encoding="utf-8")
    return [tuple(line.split("\t")) for line in text.splitlines()]


# --- input validation (no souffle invocation needed) ---


def test_run_inference_rejects_missing_dir(tmp_path):
    with pytest.raises(InferenceError, match="does not exist"):
        run_inference(tmp_path / "missing-edb")


def test_run_inference_rejects_non_edb_dir(tmp_path):
    other = tmp_path / "not-edb"
    other.mkdir()
    with pytest.raises(InferenceError, match="expected an 'edb'"):
        run_inference(other)


def test_run_inference_rejects_edb_dir_without_facts(tmp_path):
    edb = tmp_path / "edb"
    edb.mkdir()
    with pytest.raises(InferenceError, match="missing fact file"):
        run_inference(edb)


# --- end-to-end (require souffle on PATH) ---


@requires_souffle
def test_run_inference_creates_idb_directory_and_files(edb_base_dir):
    metadata_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    edb_dir = metadata_path.parent

    idb_dir = run_inference(edb_dir)

    assert idb_dir.is_dir()
    assert idb_dir.name == "idb"
    assert idb_dir.parent == edb_dir.parent  # same session directory
    assert (idb_dir / EDB_FILENAME).exists()
    assert (idb_dir / PACKAGE_EDB_FILENAME).exists()


@requires_souffle
def test_run_inference_substitutes_all_placeholders(edb_base_dir):
    metadata_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    edb_dir = metadata_path.parent
    session_dir = edb_dir.parent

    run_inference(edb_dir)

    merged = session_dir / MERGED_FILENAME
    assert merged.exists()
    text = merged.read_text(encoding="utf-8")
    for placeholder in (
        "<edb-metadata-facts>",
        "<edb-package-facts>",
        "<idb-metadata-facts>",
        "<idb-package-facts>",
    ):
        assert placeholder not in text, f"{placeholder} was not substituted"
    # Paths are substituted as session-relative, not absolute.
    assert f"edb/{EDB_FILENAME}" in text
    assert f"idb/{EDB_FILENAME}" in text
    assert str(session_dir.resolve()) not in text


@requires_souffle
def test_run_inference_lifts_metadata_with_r_metadata_prefix(edb_base_dir):
    metadata_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    edb_dir = metadata_path.parent

    edb_ids = {row[0] for row in _read_rows(metadata_path)}
    idb_dir = run_inference(edb_dir)
    idb_ids = {row[0] for row in _read_rows(idb_dir / EDB_FILENAME)}

    # the metadata rule rewrites each EDB id to R_METADATA[<id>].
    assert idb_ids == {f"R_METADATA[{fid}]" for fid in edb_ids}


@requires_souffle
def test_run_inference_lifts_package_with_r_package_prefix(edb_base_dir):
    metadata_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    edb_dir = metadata_path.parent

    edb_package_rows = _read_rows(edb_dir / PACKAGE_EDB_FILENAME)
    idb_dir = run_inference(edb_dir)
    idb_package_rows = _read_rows(idb_dir / PACKAGE_EDB_FILENAME)

    # Each EDB package fact (id, key, value) becomes (R_PACKAGE[id], key, value).
    expected = [
        (f"R_PACKAGE[{fid}]", key, value)
        for fid, key, value in edb_package_rows
    ]
    assert sorted(idb_package_rows) == sorted(expected)
