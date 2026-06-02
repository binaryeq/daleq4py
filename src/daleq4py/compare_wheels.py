# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Compare two Python wheels using the daleq4py pipeline.

The comparison partitions every file in a wheel into three groups and applies
a different equality test to each:

1. **dist-info metadata** -- for both wheels, run the full pipeline
   (:mod:`daleq4py.extract_edb` -> :mod:`daleq4py.inference` ->
   :mod:`daleq4py.project_idb`) and then compare the reduced markdown
   summaries (``normalisation-summary-reduced.md``) character by character.
2. **``*.py`` source files** -- for each shared ``.py`` member, normalise both
   sources with :func:`daleq4py.normalise_pysrc.normalise_source` and compare
   the results character by character. Members present in only one wheel
   count as a difference.
3. **everything else** -- byte-by-byte comparison of every shared non-``.py``
   member outside ``*.dist-info``. Members present in only one wheel count as
   a difference.

The three per-group booleans are combined with ``and`` to produce the overall
result.
"""

from __future__ import annotations

import argparse
import logging
import sys
import zipfile
from pathlib import Path

from daleq4py.extract_edb import (
    DEFAULT_BASE_DIR,
    DIST_INFO_SUFFIX,
    extract_edb,
)
from daleq4py.inference import (
    InferenceError,
    MERGED_FILENAME,
    run_inference,
)
from daleq4py.normalise_pysrc import normalise_source
from daleq4py.project_idb import project_idb
from daleq4py.wheel import WheelValidationError, validate_wheel

logger = logging.getLogger("daleq4py.compare_wheels")

PY_SUFFIX = ".py"


def _py_member_paths(archive_path: Path) -> set[str]:
    """Return the set of ``.py`` member paths in a wheel or zip archive."""
    paths: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if info.filename.endswith(PY_SUFFIX):
                paths.add(info.filename)
    return paths


def _classify_members(wheel: Path) -> dict[str, list[str]]:
    """Group wheel members into dist-info, .py, and other buckets."""
    dist_info: list[str] = []
    py_files: list[str] = []
    other: list[str] = []
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename
            top = name.split("/", 1)[0]
            if top.endswith(DIST_INFO_SUFFIX):
                dist_info.append(name)
            elif name.endswith(PY_SUFFIX):
                py_files.append(name)
            else:
                other.append(name)
    return {"dist_info": dist_info, "py_files": py_files, "other": other}


def _run_metadata_pipeline(
    wheel: Path, base_dir: str | Path, src: Path | None = None,
) -> dict[str, Path]:
    """Run extract-edb / inference / project-idb for one wheel.

    Returns the paths the caller will want to inspect or report later. ``src``
    is forwarded to :func:`extract_edb` so the ``@src-*`` synthetic facts are
    populated in the EDB.
    """
    content_tsv = extract_edb(wheel, base_dir=base_dir, src=src)
    edb_dir = content_tsv.parent
    session_dir = edb_dir.parent
    idb_dir = run_inference(edb_dir)
    summary = project_idb(idb_dir, remove_derivation=False)
    summary_reduced = project_idb(idb_dir, remove_derivation=True)
    return {
        "edb_dir": edb_dir,
        "idb_dir": idb_dir,
        "summary": summary,
        "summary_reduced": summary_reduced,
        "merged_rules": session_dir / MERGED_FILENAME,
    }


def _compare_py_members(
    wheel_a: Path, wheel_b: Path, names: list[str]
) -> list[str]:
    """Normalise and compare each shared .py member. Returns differing names."""
    mismatches: list[str] = []
    with zipfile.ZipFile(wheel_a) as za, zipfile.ZipFile(wheel_b) as zb:
        for name in names:
            try:
                norm_a = normalise_source(
                    za.read(name).decode("utf-8", errors="replace")
                )
                norm_b = normalise_source(
                    zb.read(name).decode("utf-8", errors="replace")
                )
            except SyntaxError:
                logger.error("syntax error normalising %s", name, exc_info=True)
                mismatches.append(name)
                continue
            if norm_a != norm_b:
                mismatches.append(name)
    return mismatches


def _compare_byte_members(
    wheel_a: Path, wheel_b: Path, names: list[str]
) -> list[str]:
    """Byte-by-byte compare each shared member. Returns differing names."""
    mismatches: list[str] = []
    with zipfile.ZipFile(wheel_a) as za, zipfile.ZipFile(wheel_b) as zb:
        for name in names:
            if za.read(name) != zb.read(name):
                mismatches.append(name)
    return mismatches


def compare_wheels(
    wheel_a: str | Path,
    wheel_b: str | Path,
    src: str | Path | None = None,
    base_dir: str | Path = DEFAULT_BASE_DIR,
) -> tuple[bool, dict]:
    """Compare two wheels via the daleq4py pipeline.

    ``src`` is an optional "trusted" wheel/zip whose ``.py`` members define a
    baseline set of source files legitimately expected in a built wheel. When
    provided, any ``.py`` member of ``wheel_a`` or ``wheel_b`` that is not in
    the baseline is flagged in ``info`` as suspicious. ``src`` does NOT
    influence the three equality booleans or the overall result.

    Returns ``(overall_equal, info)``. ``info`` carries the paths to the input
    wheels, EDB / IDB directories, both projections (full and reduced) and the
    merged Soufflé file (``mergedEDBAndRules.souffle``) for both wheels, plus
    the per-group booleans, the names of any members that did not match, and
    (when ``src`` was given) the lists of suspicious ``.py`` members.
    """
    a = validate_wheel(str(wheel_a))
    b = validate_wheel(str(wheel_b))

    src_path: Path | None = None
    src_py_paths: set[str] | None = None
    if src is not None:
        candidate = Path(src).expanduser()
        if not candidate.is_file():
            raise WheelValidationError(f"src is not a file: {src}")
        if not zipfile.is_zipfile(candidate):
            raise WheelValidationError(f"src is not a valid zip: {src}")
        src_path = candidate.resolve()
        src_py_paths = _py_member_paths(src_path)

    logger.info("comparing wheels: %s vs %s", a, b)
    if src_path is not None:
        logger.info(
            "src baseline: %s (%d .py member(s))", src_path, len(src_py_paths)
        )

    members_a = _classify_members(a)
    members_b = _classify_members(b)

    # (1) dist-info metadata -- run the full pipeline on each side, then
    # compare the reduced markdown summaries char-by-char.
    paths_a = _run_metadata_pipeline(a, base_dir, src=src_path)
    paths_b = _run_metadata_pipeline(b, base_dir, src=src_path)
    metadata_equal = paths_a["summary_reduced"].read_text(
        encoding="utf-8"
    ) == paths_b["summary_reduced"].read_text(encoding="utf-8")

    # (2) .py files -- the set of names must match and each pair must
    # normalise to the same string.
    py_a = set(members_a["py_files"])
    py_b = set(members_b["py_files"])
    py_only_in_a = sorted(py_a - py_b)
    py_only_in_b = sorted(py_b - py_a)
    py_common = sorted(py_a & py_b)
    py_mismatches = _compare_py_members(a, b, py_common)
    py_files_equal = (
        not py_only_in_a and not py_only_in_b and not py_mismatches
    )

    # (3) everything else -- byte equality on the shared set.
    other_a = set(members_a["other"])
    other_b = set(members_b["other"])
    other_only_in_a = sorted(other_a - other_b)
    other_only_in_b = sorted(other_b - other_a)
    other_common = sorted(other_a & other_b)
    other_mismatches = _compare_byte_members(a, b, other_common)
    other_files_equal = (
        not other_only_in_a and not other_only_in_b and not other_mismatches
    )

    # Trust check (only when src was provided): any .py member of a/b not
    # present in the src baseline is suspicious. This does not affect
    # ``overall`` -- it is informational and reported alongside.
    py_unexpected_in_a: list[str] = []
    py_unexpected_in_b: list[str] = []
    if src_py_paths is not None:
        py_unexpected_in_a = sorted(set(members_a["py_files"]) - src_py_paths)
        py_unexpected_in_b = sorted(set(members_b["py_files"]) - src_py_paths)

    overall = metadata_equal and py_files_equal and other_files_equal

    info: dict = {
        "wheels": {"a": a, "b": b},
        "src": src_path,
        "edb_dirs": {"a": paths_a["edb_dir"], "b": paths_b["edb_dir"]},
        "idb_dirs": {"a": paths_a["idb_dir"], "b": paths_b["idb_dir"]},
        "summaries": {"a": paths_a["summary"], "b": paths_b["summary"]},
        "summaries_reduced": {
            "a": paths_a["summary_reduced"],
            "b": paths_b["summary_reduced"],
        },
        "merged_rules": {
            "a": paths_a["merged_rules"],
            "b": paths_b["merged_rules"],
        },
        "metadata_equal": metadata_equal,
        "py_files_equal": py_files_equal,
        "other_files_equal": other_files_equal,
        "py_files_mismatches": py_mismatches,
        "py_files_only_in_a": py_only_in_a,
        "py_files_only_in_b": py_only_in_b,
        "py_files_unexpected_in_a": py_unexpected_in_a,
        "py_files_unexpected_in_b": py_unexpected_in_b,
        "other_files_mismatches": other_mismatches,
        "other_files_only_in_a": other_only_in_a,
        "other_files_only_in_b": other_only_in_b,
    }

    logger.info(
        "result: equal=%s (metadata=%s, py=%s, other=%s)",
        overall,
        metadata_equal,
        py_files_equal,
        other_files_equal,
    )
    return overall, info


# --- CLI ---


_ARTEFACT_KEYS = (
    "wheels",
    "edb_dirs",
    "idb_dirs",
    "summaries",
    "summaries_reduced",
    "merged_rules",
)


def _print_report(equal: bool, info: dict) -> None:
    """Pretty-print the comparison result and the artefact paths."""
    print(f"equal: {equal}")
    print(f"  metadata_equal:    {info['metadata_equal']}")
    print(f"  py_files_equal:    {info['py_files_equal']}")
    print(f"  other_files_equal: {info['other_files_equal']}")
    print()
    print("artefacts:")
    for key in _ARTEFACT_KEYS:
        print(f"  {key}:")
        print(f"    a: {info[key]['a']}")
        print(f"    b: {info[key]['b']}")

    def _print_diffs(label: str, only_a: list[str], only_b: list[str], diff: list[str]) -> None:
        if not (only_a or only_b or diff):
            return
        print()
        print(f"{label} differences:")
        for name in only_a:
            print(f"  only in a: {name}")
        for name in only_b:
            print(f"  only in b: {name}")
        for name in diff:
            print(f"  differing: {name}")

    _print_diffs(
        "py file",
        info["py_files_only_in_a"],
        info["py_files_only_in_b"],
        info["py_files_mismatches"],
    )
    _print_diffs(
        "other file",
        info["other_files_only_in_a"],
        info["other_files_only_in_b"],
        info["other_files_mismatches"],
    )

    if info.get("src") is not None:
        print()
        print(f"src baseline: {info['src']}")
        unexpected_a = info["py_files_unexpected_in_a"]
        unexpected_b = info["py_files_unexpected_in_b"]
        if not (unexpected_a or unexpected_b):
            print("  no suspicious .py members")
        for name in unexpected_a:
            print(f"  suspicious in a: {name}")
        for name in unexpected_b:
            print(f"  suspicious in b: {name}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compare-wheels",
        description=(
            "Compare two Python wheels: dist-info metadata via the EDB / "
            "Soufflé / projection pipeline (reduced summaries compared "
            "char-by-char), .py sources after normalisation, and any other "
            "files byte-by-byte."
        ),
    )
    parser.add_argument(
        "wheel_a",
        metavar="WHEEL_A",
        help="path to the first Python wheel (.whl) to compare",
    )
    parser.add_argument(
        "wheel_b",
        metavar="WHEEL_B",
        help="path to the second Python wheel (.whl) to compare",
    )
    parser.add_argument(
        "--src",
        metavar="ZIP",
        default=None,
        help=(
            "path to a 'trusted' wheel/zip whose .py members define the "
            "baseline set of source files legitimately expected in a built "
            "wheel; any .py member of WHEEL_A or WHEEL_B not present in this "
            "baseline is flagged as suspicious. May be the same path as "
            "WHEEL_A, WHEEL_B, or any other zip"
        ),
    )
    parser.add_argument(
        "--base-dir",
        default=DEFAULT_BASE_DIR,
        metavar="DIR",
        help=(
            "root directory for EDB / IDB / projection artefacts; a relative "
            f"path is resolved against the project root (default: {DEFAULT_BASE_DIR})"
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable verbose (debug) logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Exit code: 0 equal, 1 not equal, 2 error."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        equal, info = compare_wheels(
            args.wheel_a,
            args.wheel_b,
            src=args.src,
            base_dir=args.base_dir,
        )
    except (WheelValidationError, InferenceError, FileNotFoundError) as exc:
        logger.error("%s", exc)
        return 2

    _print_report(equal, info)
    return 0 if equal else 1


if __name__ == "__main__":
    sys.exit(main())
