# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Tests for content EDB extraction from wheels."""

import re

import pytest
from sample_data import (
    ARROW_PYPI,
    AUTOPEP8_PYPI,
    COLORLOG_MACARON,
    COLORLOG_OSSR,
    COLORLOG_PYPI,
)

from daleq4py.extract_edb import (
    KEY_NORM_SHA256,
    KEY_SHA256,
    KEY_SRC_EXISTS,
    KEY_SRC_EXISTS_MOVED,
    KEY_SRC_NORM_SHA256,
    KEY_SRC_SHA256,
    PACKAGE_EDB_FILENAME,
    PROJECT_ROOT,
    extract_edb,
)
from daleq4py.wheel import WheelValidationError

_FACT_ID = re.compile(r"^F\d+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _read_rows(tsv_path):
    """Parse the TSV into a list of column tuples (one per row)."""
    text = tsv_path.read_text(encoding="utf-8")
    return [tuple(line.split("\t")) for line in text.splitlines()]


# --- file layout ---


def test_extract_edb_writes_tsv_at_expected_path(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)

    assert edb_path.exists()
    assert edb_path.name == "content.tsv"
    # <project>/<base_dir>/<wheel-name>/<session>/edb/content.tsv
    assert edb_path.parent.name == "edb"
    assert edb_path.parents[2].name == COLORLOG_PYPI.stem
    assert edb_path.parents[3] == PROJECT_ROOT / edb_base_dir


def test_extract_edb_rows_have_five_columns(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    assert rows
    assert all(len(row) == 5 for row in rows)


def test_extract_edb_first_column_is_unique_fact_id(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    content_ids = [row[0] for row in _read_rows(edb_path)]
    package_ids = [
        row[0] for row in _read_rows(edb_path.parent / PACKAGE_EDB_FILENAME)
    ]
    all_ids = content_ids + package_ids

    assert all(_FACT_ID.match(fid) for fid in all_ids)
    assert len(set(all_ids)) == len(all_ids)
    # Counter starts at F1 and is contiguous across the EDB.
    assert all_ids == [f"F{n}" for n in range(1, len(all_ids) + 1)]


def test_extract_edb_sessions_sort_newest_first(edb_base_dir):
    first = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    second = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    assert second.parents[1].name < first.parents[1].name


def test_extract_edb_rejects_invalid_wheel(edb_base_dir, tmp_path):
    with pytest.raises(WheelValidationError):
        extract_edb(tmp_path / "missing.whl", base_dir=edb_base_dir)


# --- explicit keys (recognised metadata files) ---


def test_extract_edb_captures_key_value_metadata(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    wheel_keys = {key for _id, file, _path, key, _v in rows if file == "WHEEL"}
    assert "wheel-version" in wheel_keys


def test_extract_edb_normalises_metadata_field_names(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    metadata_keys = {
        key for _id, file, _path, key, _v in rows if file == "METADATA"
    }
    assert {"metadata_version", "name", "version"} <= metadata_keys


def test_extract_edb_parses_record_per_line(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    # RECORD rows whose key isn't one of the @synthetic keys.
    record_explicit = [
        row for row in rows
        if row[1] == "RECORD" and not row[3].startswith("@")
    ]
    assert len(record_explicit) > 1
    for _id, _file, _path, key, value in record_explicit:
        assert key
        assert "," not in key
        if value:
            assert value.startswith("sha256=") or value.startswith(",")


def test_extract_edb_unstructured_files_have_no_explicit_rows(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    # LICENSE is plain prose; under the new schema it contributes only
    # synthetic facts (no explicit empty-key row).
    license_explicit = [
        row for row in rows
        if row[1] == "LICENSE" and not row[3].startswith("@")
    ]
    assert license_explicit == []


# --- coverage: walk EVERY member, not just dist-info ---


def test_extract_edb_covers_dist_info_and_source_files(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    paths = {row[2] for row in rows}
    assert any(".dist-info" in p for p in paths)        # metadata side
    assert any(p == "colorlog" for p in paths)          # .py source side


# --- synthetic keys: always-on ---


def test_extract_edb_emits_sha256_for_every_member(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)

    members = {(row[1], row[2]) for row in rows}
    members_with_sha = {
        (row[1], row[2]) for row in rows if row[3] == KEY_SHA256
    }
    assert members == members_with_sha

    for _id, _file, _path, key, value in rows:
        if key == KEY_SHA256:
            assert _SHA256.match(value)


def test_extract_edb_emits_norm_sha256_for_py_sources(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    py_members = {(row[1], row[2]) for row in rows if row[1].endswith(".py")}
    assert py_members
    norm_members = {
        (row[1], row[2])
        for row in rows
        if row[3] == KEY_NORM_SHA256 and row[1].endswith(".py")
    }
    assert py_members == norm_members


# --- @src-* synthetic keys ---


def test_extract_edb_omits_src_keys_when_no_src(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    rows = _read_rows(edb_path)
    src_keys = {row[3] for row in rows if row[3].startswith("@src")}
    assert src_keys == set()


def test_extract_edb_marks_src_exists_true_for_self_baseline(edb_base_dir):
    """With src == wheel, every member's @src-exists is true."""
    edb_path = extract_edb(
        COLORLOG_PYPI, base_dir=edb_base_dir, src=COLORLOG_PYPI
    )
    rows = _read_rows(edb_path)
    src_exists_values = {
        row[4] for row in rows if row[3] == KEY_SRC_EXISTS
    }
    assert src_exists_values == {"true"}
    src_moved_values = {
        row[4] for row in rows if row[3] == KEY_SRC_EXISTS_MOVED
    }
    assert src_moved_values == {"true"}


def test_extract_edb_self_baseline_src_sha_matches_sha(edb_base_dir):
    """With src == wheel, @src/sha256 equals @sha256 for every member."""
    edb_path = extract_edb(
        COLORLOG_PYPI, base_dir=edb_base_dir, src=COLORLOG_PYPI
    )
    rows = _read_rows(edb_path)
    sha_by_member: dict[tuple[str, str], str] = {}
    src_sha_by_member: dict[tuple[str, str], str] = {}
    for _id, file, path, key, value in rows:
        if key == KEY_SHA256:
            sha_by_member[(file, path)] = value
        elif key == KEY_SRC_SHA256:
            src_sha_by_member[(file, path)] = value
    assert sha_by_member == src_sha_by_member


def test_extract_edb_marks_src_exists_false_for_unrelated_baseline(
    edb_base_dir,
):
    """colorlog vs arrow: paths don't overlap, basenames mostly don't either."""
    edb_path = extract_edb(
        COLORLOG_PYPI, base_dir=edb_base_dir, src=ARROW_PYPI
    )
    rows = _read_rows(edb_path)
    src_exists_for_colorlog_py = {
        row[4]
        for row in rows
        if row[3] == KEY_SRC_EXISTS and row[2] == "colorlog"
    }
    # No .py file under colorlog/ exists under the same path in arrow.
    assert src_exists_for_colorlog_py == {"false"}


def test_extract_edb_emits_src_norm_sha_with_src_sha(edb_base_dir):
    """When @src/sha256 is emitted for a text file, @src/norm/sha256 is too."""
    edb_path = extract_edb(
        COLORLOG_PYPI, base_dir=edb_base_dir, src=COLORLOG_PYPI
    )
    rows = _read_rows(edb_path)
    src_sha_members = {
        (row[1], row[2]) for row in rows if row[3] == KEY_SRC_SHA256
    }
    src_norm_members = {
        (row[1], row[2]) for row in rows if row[3] == KEY_SRC_NORM_SHA256
    }
    # Every .py member with @src/sha256 should also have @src/norm/sha256.
    py_src_sha = {(f, p) for (f, p) in src_sha_members if f.endswith(".py")}
    assert py_src_sha <= src_norm_members


# --- package-edb.tsv ---


def test_extract_edb_writes_package_edb_alongside_content(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    package_path = edb_path.parent / PACKAGE_EDB_FILENAME
    assert package_path.exists()
    assert package_path.parent == edb_path.parent


def test_extract_edb_package_edb_has_name_and_distinfo_rows(edb_base_dir):
    edb_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    package_path = edb_path.parent / PACKAGE_EDB_FILENAME
    rows = _read_rows(package_path)
    assert len(rows) == 2
    assert [row[1:] for row in rows] == [
        ("name", "colorlog-6.7.0"),
        ("distinfo", "colorlog-6.7.0.dist-info"),
    ]
    assert all(_FACT_ID.match(row[0]) for row in rows)


@pytest.mark.parametrize(
    "wheel,expected_name",
    [
        (COLORLOG_PYPI, "colorlog-6.7.0"),
        (ARROW_PYPI, "arrow-1.2.1"),
        (AUTOPEP8_PYPI, "autopep8-2.1.2"),
    ],
    ids=lambda v: v if isinstance(v, str) else v.name,
)
def test_extract_edb_package_name_matches_dist_info(
    wheel, expected_name, edb_base_dir
):
    edb_path = extract_edb(wheel, base_dir=edb_base_dir)
    rows = _read_rows(edb_path.parent / PACKAGE_EDB_FILENAME)
    by_key = {row[1]: row[2] for row in rows}
    assert by_key["name"] == expected_name
    assert by_key["distinfo"] == f"{expected_name}.dist-info"
    assert all(_FACT_ID.match(row[0]) for row in rows)
