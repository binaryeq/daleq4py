# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Run pairwise wheel-comparison experiments across ``sample-data/``.

The sample layout is

    <sample_dir>/<package>/<version>/<build>/<wheel>.whl

For every ``(package, version)`` group with at least two builds, this script
compares every pair of builds with :func:`daleq4py.compare_wheels.compare_wheels`
and writes one markdown report per pair to

    <results_dir>/<package>/<version>/<build_a>-vs-<build_b>.md

The pipeline artefacts produced for each pair (EDB, IDB, projections,
``mergedEDBAndRules.souffle``) land under
``<results_dir>/.artefacts/<package>/<version>/<build_a>-vs-<build_b>/`` so the
markdown can link to them with stable relative paths.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from itertools import combinations
from pathlib import Path

from daleq4py.compare_wheels import compare_wheels
from daleq4py.extract_edb import PROJECT_ROOT

logger = logging.getLogger("daleq4py.run_experiments")

DEFAULT_SAMPLE_DIR = "sample-data"
DEFAULT_RESULTS_DIR = "sample-data-results"
ARTEFACTS_SUBDIR = ".artefacts"
SUMMARY_FILENAME = "summary.md"


def _discover_wheels(sample_dir: Path) -> dict[tuple[str, str], dict[str, Path]]:
    """Return ``{(package, version): {build: wheel_path}}`` from the sample tree."""
    groups: dict[tuple[str, str], dict[str, Path]] = {}
    for wheel in sorted(sample_dir.rglob("*.whl")):
        rel = wheel.relative_to(sample_dir).parts
        # Expect <package>/<version>/<build>/<wheel>.whl
        if len(rel) < 4:
            logger.warning("skipping wheel with unexpected layout: %s", wheel)
            continue
        package, version, build = rel[0], rel[1], rel[2]
        bucket = groups.setdefault((package, version), {})
        if build in bucket:
            logger.warning(
                "multiple wheels for %s %s/%s; keeping %s",
                package, version, build, bucket[build],
            )
            continue
        bucket[build] = wheel
    return groups


def _rel(target: Path, from_file: Path) -> str:
    """Relative path string from the directory of ``from_file`` to ``target``."""
    return os.path.relpath(target, from_file.parent)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


_ARTEFACT_ROWS = (
    ("wheels", "Wheel"),
    ("edb_dirs", "EDB"),
    ("idb_dirs", "IDB"),
    ("summaries", "Projection (full)"),
    ("summaries_reduced", "Projection (reduced)"),
    ("merged_rules", "Combined rules (mergedEDBAndRules.souffle)"),
)

_DIFF_SECTIONS = (
    ("py_files_only_in_a", "Python source files only in build A"),
    ("py_files_only_in_b", "Python source files only in build B"),
    ("py_files_mismatches", "Python source files that differ after normalisation"),
    ("other_files_only_in_a", "Other files only in build A"),
    ("other_files_only_in_b", "Other files only in build B"),
    ("other_files_mismatches", "Other files that differ byte-by-byte"),
)


def _render_pair_report(
    md_path: Path,
    package: str,
    version: str,
    build_a: str,
    build_b: str,
    wheel_a: Path,
    wheel_b: Path,
    equal: bool | None,
    info: dict | None,
    error: str | None,
) -> str:
    """Build the markdown text for one comparison pair."""
    lines: list[str] = [
        f"# {package} {version}: {build_a} vs {build_b}",
        "",
        f"- Package: `{package}`",
        f"- Version: `{version}`",
        f"- Build A (`{build_a}`): [`{_rel(wheel_a, md_path)}`]({_rel(wheel_a, md_path)})",
        f"- Build B (`{build_b}`): [`{_rel(wheel_b, md_path)}`]({_rel(wheel_b, md_path)})",
        "",
        "## Result",
        "",
    ]

    if error is not None:
        lines.extend([
            "**ERROR**: the comparison pipeline raised an exception.",
            "",
            "```",
            error,
            "```",
            "",
        ])
        return "\n".join(lines) + "\n"

    assert info is not None
    lines.extend([
        "| Group | Equal |",
        "| --- | --- |",
        f"| **Overall** | **{_yes_no(equal)}** |",
        f"| Metadata (`*.dist-info`, char-by-char on reduced projection) | {_yes_no(info['metadata_equal'])} |",
        f"| Python sources (`*.py`, char-by-char after normalisation) | {_yes_no(info['py_files_equal'])} |",
        f"| Other files (byte-by-byte) | {_yes_no(info['other_files_equal'])} |",
        "",
        "## Artefacts",
        "",
        "| Artefact | Build A | Build B |",
        "| --- | --- | --- |",
    ])
    for key, label in _ARTEFACT_ROWS:
        a = _rel(info[key]["a"], md_path)
        b = _rel(info[key]["b"], md_path)
        lines.append(f"| {label} | [`{a}`]({a}) | [`{b}`]({b}) |")
    lines.append("")

    if any(info[key] for key, _ in _DIFF_SECTIONS):
        lines.append("## Differences")
        lines.append("")
        for key, heading in _DIFF_SECTIONS:
            items = info[key]
            if not items:
                continue
            lines.append(f"### {heading} ({len(items)})")
            lines.append("")
            for name in items:
                lines.append(f"- `{name}`")
            lines.append("")

    return "\n".join(lines) + "\n"


def _cell(value: bool | None) -> str:
    """Render an optional boolean for a summary-table cell."""
    if value is None:
        return "error"
    return "yes" if value else "no"


def _render_summary(summary: dict) -> str:
    """Render the top-level summary markdown for the whole experiment sweep."""
    total = summary["total"]
    equal = summary["equal"]
    different = summary["different"]
    errors = summary["errors"]
    outcomes = summary["outcomes"]

    lines: list[str] = [
        "# Wheel-comparison experiment summary",
        "",
        "## Counts",
        "",
        "| Outcome | Pairs |",
        "| --- | ---: |",
        f"| Equal (overall = true) | {equal} |",
        f"| Different (overall = false) | {different} |",
        f"| Errored | {errors} |",
        f"| **Total** | **{total}** |",
        "",
        "## Details",
        "",
        "| Package | Builds | Overall | Metadata | Python sources | Other files |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for o in outcomes:
        report_rel = os.path.relpath(o["report"], summary["results_dir"])
        builds = f"{o['build_a']} vs {o['build_b']}"
        lines.append(
            f"| `{o['package']}` {o['version']} | "
            f"[{builds}]({report_rel}) | "
            f"{_cell(o['overall'])} | "
            f"{_cell(o['metadata'])} | "
            f"{_cell(o['py_files'])} | "
            f"{_cell(o['other_files'])} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def run_experiments(sample_dir: Path, results_dir: Path) -> dict:
    """Compare every build-pair under ``sample_dir`` and write a report each.

    Returns a summary dict with the counts of equal / different / errored
    pairs and a list of per-pair outcomes.
    """
    sample_dir = sample_dir.resolve()
    results_dir = results_dir.resolve()
    artefacts_root = results_dir / ARTEFACTS_SUBDIR

    groups = _discover_wheels(sample_dir)
    logger.info(
        "found %d package/version group(s) in %s", len(groups), sample_dir
    )

    total = equal_count = diff_count = error_count = 0
    outcomes: list[dict] = []

    for (package, version), builds in sorted(groups.items()):
        if len(builds) < 2:
            logger.info(
                "skipping %s %s: only one build (%s)",
                package, version, next(iter(builds)),
            )
            continue

        for build_a, build_b in combinations(sorted(builds.keys()), 2):
            total += 1
            pair_label = f"{build_a}-vs-{build_b}"
            md_path = results_dir / package / version / f"{pair_label}.md"
            pair_base = artefacts_root / package / version / pair_label
            wheel_a, wheel_b = builds[build_a], builds[build_b]

            logger.info(
                "comparing %s %s: %s vs %s", package, version, build_a, build_b
            )

            equal: bool | None
            info: dict | None
            error: str | None
            try:
                equal, info = compare_wheels(wheel_a, wheel_b, base_dir=pair_base)
                error = None
            # broad catch: one bad pair must not abort the rest of the sweep.
            except Exception as exc:
                logger.error(
                    "comparison failed for %s %s %s",
                    package, version, pair_label, exc_info=True,
                )
                equal, info = None, None
                error = f"{type(exc).__name__}: {exc}"

            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(
                _render_pair_report(
                    md_path, package, version, build_a, build_b,
                    wheel_a, wheel_b, equal, info, error,
                ),
                encoding="utf-8",
            )

            if error is not None:
                error_count += 1
                status = "error"
            elif equal:
                equal_count += 1
                status = "equal"
            else:
                diff_count += 1
                status = "different"
            outcomes.append({
                "package": package,
                "version": version,
                "build_a": build_a,
                "build_b": build_b,
                "status": status,
                "overall": equal,
                "metadata": info["metadata_equal"] if info else None,
                "py_files": info["py_files_equal"] if info else None,
                "other_files": info["other_files_equal"] if info else None,
                "report": md_path,
            })

    summary = {
        "total": total,
        "equal": equal_count,
        "different": diff_count,
        "errors": error_count,
        "outcomes": outcomes,
        "results_dir": results_dir,
    }
    summary_path = results_dir / SUMMARY_FILENAME
    summary_path.write_text(_render_summary(summary), encoding="utf-8")
    logger.info(
        "done: %d pair(s) compared (%d equal, %d different, %d errored); "
        "summary written to %s",
        total, equal_count, diff_count, error_count, summary_path,
    )
    return summary


# --- CLI ---


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run-experiments",
        description=(
            "Run pairwise compare-wheels experiments across every "
            "<package>/<version> group in a sample-data directory and write "
            "one markdown report per build pair."
        ),
    )
    parser.add_argument(
        "--sample-dir",
        type=Path,
        default=Path(DEFAULT_SAMPLE_DIR),
        metavar="DIR",
        help=(
            "directory containing the sample wheels in "
            "<package>/<version>/<build>/<wheel>.whl layout; a relative path "
            f"is resolved against the project root (default: {DEFAULT_SAMPLE_DIR})"
        ),
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path(DEFAULT_RESULTS_DIR),
        metavar="DIR",
        help=(
            "directory under which the markdown reports and pipeline "
            "artefacts are written; a relative path is resolved against the "
            f"project root (default: {DEFAULT_RESULTS_DIR})"
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
    """Entry point. Returns 0 unless at least one pair errored (then 1)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    sample_dir = args.sample_dir
    if not sample_dir.is_absolute():
        sample_dir = (PROJECT_ROOT / sample_dir).resolve()
    if not sample_dir.is_dir():
        logger.error("sample-dir does not exist: %s", sample_dir)
        return 2

    results_dir = args.results_dir
    if not results_dir.is_absolute():
        results_dir = (PROJECT_ROOT / results_dir).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)

    summary = run_experiments(sample_dir, results_dir)

    print(f"pairs compared: {summary['total']}")
    print(f"  equal:     {summary['equal']}")
    print(f"  different: {summary['different']}")
    print(f"  errors:    {summary['errors']}")
    print(f"reports under: {results_dir}")
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
