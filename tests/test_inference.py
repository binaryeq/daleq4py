# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Tests for souffle inference on extracted EDBs."""

import shutil

import pytest
from sample_data import COLORLOG_PYPI, COLORLOG_6_10_1_PYPI

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
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    edb_dir = content_path.parent

    idb_dir = run_inference(edb_dir)

    assert idb_dir.is_dir()
    assert idb_dir.name == "idb"
    assert idb_dir.parent == edb_dir.parent  # same session directory
    assert (idb_dir / EDB_FILENAME).exists()
    assert (idb_dir / PACKAGE_EDB_FILENAME).exists()


@requires_souffle
def test_run_inference_substitutes_all_placeholders(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    edb_dir = content_path.parent
    session_dir = edb_dir.parent

    run_inference(edb_dir)

    merged = session_dir / MERGED_FILENAME
    assert merged.exists()
    text = merged.read_text(encoding="utf-8")
    for placeholder in (
        "<edb-content-facts>",
        "<edb-package-facts>",
        "<idb-content-facts>",
        "<idb-package-facts>",
        "<text-extensions-facts>",
    ):
        assert placeholder not in text, f"{placeholder} was not substituted"
    # The text-extensions file is referenced by its absolute source-tree path.
    assert "text_extensions.txt" in text
    # Paths are substituted as session-relative, not absolute.
    assert f"edb/{EDB_FILENAME}" in text
    assert f"idb/{EDB_FILENAME}" in text
    assert str(session_dir.resolve()) not in text


@requires_souffle
def test_run_inference_lifts_content_with_r_content_prefix(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    edb_dir = content_path.parent

    edb_ids = {row[0] for row in _read_rows(content_path)}
    idb_dir = run_inference(edb_dir)
    idb_ids = {row[0] for row in _read_rows(idb_dir / EDB_FILENAME)}

    # Every IDB row with the R_CONTENT prefix is the lift of some EDB row.
    # The IDB is a *subset* of the lifted EDB because metadata-normalisation
    # rules can drop facts via idb.remove_content (e.g. the WHEEL generator
    # entry for whitelisted build tools).
    idb_r_content_ids = {id for id in idb_ids if id.startswith("R_CONTENT[")}
    assert idb_r_content_ids <= {f"R_CONTENT[{fid}]" for fid in edb_ids}
    # Sanity: the lift produced something.
    assert idb_r_content_ids


def _write_edb(edb_dir, content_rows, package_rows):
    """Write a hand-crafted edb/ directory (content.tsv + package.tsv)."""
    edb_dir.mkdir(parents=True, exist_ok=True)
    (edb_dir / EDB_FILENAME).write_text(
        "".join("\t".join(r) + "\n" for r in content_rows), encoding="utf-8"
    )
    (edb_dir / PACKAGE_EDB_FILENAME).write_text(
        "".join("\t".join(r) + "\n" for r in package_rows), encoding="utf-8"
    )


@requires_souffle
def test_normalisation_rules_drop_raw_sha_for_py_and_text_files(tmp_path):
    """R_NORMALIZE_PY / R_NORMALIZE_TXT remove @sha256 for source and text
    files (by extension), but leave binary members untouched."""
    edb_dir = tmp_path / "session" / "edb"
    _write_edb(
        edb_dir,
        content_rows=[
            ("F1", "app.js", "pkg", "@sha256", "aaa"),
            ("F2", "app.js", "pkg", "@norm/sha256", "nnn"),
            ("F3", "mod.py", "pkg", "@sha256", "bbb"),
            ("F4", "logo.png", "pkg", "@sha256", "ccc"),
            ("F5", "conf.properties", "pkg", "@sha256", "ddd"),
        ],
        package_rows=[
            ("F6", "name", "demo-1.0"),
            ("F7", "distinfo", "demo-1.0.dist-info"),
        ],
    )

    idb_dir = run_inference(edb_dir)
    rows = _read_rows(idb_dir / EDB_FILENAME)
    # (file, key) pairs that survived into the IDB.
    surviving = {(file, key) for _id, file, _path, key, _value in rows}

    # raw @sha256 dropped for the .js and .properties (text) and .py members.
    assert ("app.js", "@sha256") not in surviving
    assert ("conf.properties", "@sha256") not in surviving
    assert ("mod.py", "@sha256") not in surviving
    # the normalised hash for the text file is kept.
    assert ("app.js", "@norm/sha256") in surviving
    # binary member is untouched.
    assert ("logo.png", "@sha256") in surviving


@requires_souffle
def test_normalisation_rules_keep_normalised_requires_dist_from_metadata(tmp_path):
    edb_dir = tmp_path / "session" / "edb"
    _write_edb(
        edb_dir,
        content_rows=[
            ("F1", "METADATA", "demo-1.0.dist-info", "requires_dist", "Foo_Bar >= 1.2.3"),
            ("F2", "METADATA", "demo-1.0.dist-info", "@norm/requires_dist", "foo-bar>=1.2.3")
        ],
        package_rows=[
            ("F3", "name", "demo-1.0"),
            ("F4", "distinfo", "demo-1.0.dist-info"),
        ],
    )

    idb_dir = run_inference(edb_dir)
    rows = _read_rows(idb_dir / EDB_FILENAME)
    # (file, key) pairs that survived into the IDB.
    surviving = {(file, key) for _id, file, _path, key, _value in rows}

    # Normalised Requires-Dist: value from EDB should survive into IDB
    assert ("METADATA", "@norm/requires_dist") in surviving


@requires_souffle
def test_run_inference_lifts_package_with_r_package_prefix(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    edb_dir = content_path.parent

    edb_package_rows = _read_rows(edb_dir / PACKAGE_EDB_FILENAME)
    idb_dir = run_inference(edb_dir)
    idb_package_rows = _read_rows(idb_dir / PACKAGE_EDB_FILENAME)

    # Each EDB package fact (id, key, value) becomes (R_PACKAGE[id], key, value).
    expected = [
        (f"R_PACKAGE[{fid}]", key, value)
        for fid, key, value in edb_package_rows
    ]
    assert sorted(idb_package_rows) == sorted(expected)


@requires_souffle
def test_run_inference_moves_license_to_license_subdir(edb_base_dir):
    content_path = extract_edb(COLORLOG_PYPI, base_dir=edb_base_dir)
    edb_dir = content_path.parent

    edb = {row for row in _read_rows(content_path)}
    idb_dir = run_inference(edb_dir)
    idb = {row for row in _read_rows(idb_dir / EDB_FILENAME)}

    # Sanity: The license file for colorlog-6.7.0 lives directly in the *.dist-info/ dir
    assert any(row for row in edb if row[1:3] == ("LICENSE", "colorlog-6.7.0.dist-info"))

    # The license file should appear in the licenses/ subdir in the IDB, and only there
    assert any(row for row in idb if row[1:3] == ("LICENSE", "colorlog-6.7.0.dist-info/licenses"))
    assert not any(row for row in idb if row[1:3] == ("LICENSE", "colorlog-6.7.0.dist-info"))


@requires_souffle
def test_run_inference_leaves_license_already_in_license_subdir_in_place(edb_base_dir):
    content_path = extract_edb(COLORLOG_6_10_1_PYPI, base_dir=edb_base_dir)
    edb_dir = content_path.parent

    edb = {row for row in _read_rows(content_path)}
    idb_dir = run_inference(edb_dir)
    idb = {row for row in _read_rows(idb_dir / EDB_FILENAME)}

    # Sanity: The license file for colorlog-6.10.1 already lives in *.dist-info/licenses/
    assert any(row for row in edb if row[1:3] == ("LICENSE", "colorlog-6.10.1.dist-info/licenses"))

    # The license file should still appear in the licenses/ subdir in the IDB, and only there
    assert any(row for row in idb if row[1:3] == ("LICENSE", "colorlog-6.10.1.dist-info/licenses"))
    assert not any(row for row in idb if row[1:3] == ("LICENSE", "colorlog-6.10.1.dist-info"))
