"""Regression tests for the encoding-cookie false positive (issue 20).

Python source must be interpreted using its declared encoding before
normalisation. These tests fail while executable assignments can be discarded
as comments. Only the locally generated fixture is executed; its payload
assigns a string to VALUE.
"""

from __future__ import annotations

import ast
import base64
import csv
import hashlib
import importlib.util
import io
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from daleq4py.compare_wheels import _compare_py_members, compare_wheels
from daleq4py.extract_edb import _normalise_for_hash
from daleq4py.normalise_pysrc import main as normalise_main


@pytest.fixture(params=[False, True], ids=["cookie-first-line", "cookie-second-line"])
def sources(request):
    prefix = b"#!/usr/bin/env python\n" if request.param else b""
    common = prefix + b"# -*- coding: utf-7 -*-\nVALUE = 'safe'\n"
    return common, common + b"# +AAo-VALUE = 'evil'\n"


def _make_wheel(directory: Path, source: bytes) -> Path:
    """Build an installable wheel, including accurate per-member RECORD hashes."""
    directory.mkdir(parents=True)
    wheel = directory / "q3_fixture-1.0-py3-none-any.whl"
    dist_info = "q3_fixture-1.0.dist-info"
    members = {
        "q3_fixture.py": source,
        f"{dist_info}/METADATA": (
            b"Metadata-Version: 2.1\nName: q3-fixture\nVersion: 1.0\n\n"
        ),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: setuptools\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n\n"
        ),
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, data in members.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
        writer.writerow((
            name, "sha256=" + digest.rstrip(b"=").decode("ascii"), len(data),
        ))
    writer.writerow((f"{dist_info}/RECORD", "", ""))
    members[f"{dist_info}/RECORD"] = record.getvalue().encode("utf-8")
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return wheel


def _installed_value(wheel: Path, target: Path) -> str:
    """Install offline into a private directory, then import in a fresh process."""
    installed = subprocess.run(
        [
            sys.executable, "-I", "-m", "pip", "--isolated", "install",
            "--disable-pip-version-check", "--no-index", "--no-deps",
            "--no-compile", "--target", str(target), str(wheel),
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    imported = subprocess.run(
        [
            sys.executable, "-I", "-B", "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "import q3_fixture; print(q3_fixture.VALUE)",
            str(target),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr
    return imported.stdout.strip()


def test_python_hash_normalisation_preserves_encoded_assignment(sources):
    safe, hidden = sources
    assert safe != hidden
    assert "# \nVALUE = 'evil'" in hidden.decode("utf-7")
    assert _normalise_for_hash("q3_fixture.py", safe) != _normalise_for_hash(
        "q3_fixture.py", hidden
    )


def test_python_member_comparison_detects_encoded_assignment(tmp_path, sources):
    safe, hidden = sources
    wheel_a = _make_wheel(tmp_path / "safe", safe)
    wheel_b = _make_wheel(tmp_path / "hidden", hidden)

    assert _compare_py_members(wheel_a, wheel_b, ["q3_fixture.py"]) == [
        "q3_fixture.py",
    ]


def test_normalise_cli_preserves_encoded_assignment(tmp_path, sources):
    _, hidden = sources
    source = tmp_path / "q3_fixture.py"
    source.write_bytes(hidden)
    output = tmp_path / "normalised"

    assert normalise_main([str(source), "-o", str(output)]) == 0
    normalised = (output / source.name).read_bytes()
    assert ast.dump(ast.parse(normalised)) == ast.dump(ast.parse(hidden))


@pytest.mark.skipif(
    shutil.which("souffle") is None, reason="souffle executable not on PATH",
)
@pytest.mark.skipif(
    importlib.util.find_spec("pip") is None,
    reason="pip needed for local fixture installation",
)
def test_wheels_with_different_installed_behaviour_compare_unequal(tmp_path, sources):
    safe, hidden = sources
    wheel_a = _make_wheel(tmp_path / "safe", safe)
    wheel_b = _make_wheel(tmp_path / "hidden", hidden)

    # Establish the actual runtime difference before checking the comparator.
    assert _installed_value(wheel_a, tmp_path / "installed-safe") == "safe"
    assert _installed_value(wheel_b, tmp_path / "installed-hidden") == "evil"

    # Exercise real extraction, Souffle inference and projection, without mocks.
    equal, info = compare_wheels(
        wheel_a, wheel_b, src=wheel_a, base_dir=tmp_path / "comparison",
    )
    assert equal is False
    assert info["metadata_equal"] is False
    assert info["py_files_equal"] is False
    assert info["text_files_equal"] is True
    assert info["other_files_equal"] is True
    assert info["py_files_mismatches"] == ["q3_fixture.py"]
    assert info["py_files_unexpected_in_b"] == []
