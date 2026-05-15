"""Tests for metadata EDB extraction from wheels."""

import pytest
from sample_data import COLORLOG_PYPI

from daleq4py.extract_edb import PROJECT_ROOT, extract_edb
from daleq4py.wheel import WheelValidationError


def _read_rows(tsv_path):
    """Parse the TSV into a list of ``(file, path, key, value)`` tuples."""
    text = tsv_path.read_text(encoding="utf-8")
    return [tuple(line.split("\t")) for line in text.splitlines()]


def test_extract_edb_writes_tsv_at_expected_path(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)

    assert edb_path.exists()
    assert edb_path.name == "metadata-edb.tsv"
    # <project>/<base_dir>/<wheel-name>/<session>/edb/metadata-edb.tsv
    assert edb_path.parent.name == "edb"
    assert edb_path.parents[2].name == COLORLOG_PYPI.stem
    assert edb_path.parents[3] == PROJECT_ROOT / edb_base_dir


def test_extract_edb_rows_have_four_columns(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    assert rows  # some metadata was extracted
    assert all(len(row) == 4 for row in rows)


def test_extract_edb_captures_key_value_metadata(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    # WHEEL is a key-value metadata file present in every wheel.
    # packaging.metadata.parse_email lowercases unparsed field names.
    wheel_keys = {key for file, path, key, value in rows if file == "WHEEL"}
    assert "wheel-version" in wheel_keys


def test_extract_edb_normalises_metadata_field_names(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    # parse_email canonicalises recognised METADATA fields to snake_case.
    metadata_keys = {key for file, path, key, value in rows if file == "METADATA"}
    assert {"metadata_version", "name", "version"} <= metadata_keys


def test_extract_edb_captures_unstructured_files_as_value(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    # RECORD has no key-value structure: stored with an empty key.
    record_rows = [row for row in rows if row[0] == "RECORD"]
    assert record_rows
    assert all(key == "" and value for file, path, key, value in record_rows)


def test_extract_edb_path_uses_dist_info_directory(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    assert all(".dist-info" in path for file, path, key, value in rows)


def test_extract_edb_sessions_sort_newest_first(edb_base_dir):
    first = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    second = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    # the later extraction gets a lexicographically smaller session id
    assert second.parents[1].name < first.parents[1].name


def test_extract_edb_rejects_invalid_wheel(edb_base_dir, tmp_path):
    with pytest.raises(WheelValidationError):
        extract_edb(tmp_path / "missing.whl", base_dir=edb_base_dir)
