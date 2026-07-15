# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Render a markdown summary of an IDB folder.

Given the ``idb/`` directory produced by :mod:`daleq4py.inference`, this
module writes ``<session>/normalisation-summary.md`` with one section per
IDB predicate (one section per ``*.tsv`` file). The section header is the
predicate name -- the TSV filename stem -- and the body is a markdown table
whose column headers are inferred from the matching ``.decl`` declaration in
any ``rules/*.souffle`` file.

When ``remove_derivation=True`` the output filename gains a ``-reduced``
suffix and the leading ``id`` column (the rule provenance trace) is stripped
from every table.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from daleq4py.extract_edb import PROJECT_ROOT, extract_edb

logger = logging.getLogger("daleq4py")

RULES_DIR = PROJECT_ROOT / "rules"
SUMMARY_FILENAME = "normalisation-summary.md"
SUMMARY_REDUCED_FILENAME = "normalisation-summary-reduced.md"
ID_COLUMN = "id"

# ``.decl <name>(<col1>: <type>, ...)``. Soufflé identifiers are letters,
# digits and underscores; we ignore the types and keep just the column names.
_DECL_RE = re.compile(r"\.decl\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")


def _parse_decls(rules_dir: Path) -> dict[str, list[str]]:
    """Return ``{predicate_name: [column_name, ...]}`` from every rules file.

    A predicate declared in multiple files is taken from whichever file the
    glob visits first; in practice all declarations of the same predicate
    must share a shape anyway, otherwise Soufflé wouldn't compile.
    """
    decls: dict[str, list[str]] = {}
    for rule_file in sorted(rules_dir.glob("*.souffle")):
        text = rule_file.read_text(encoding="utf-8")
        for match in _DECL_RE.finditer(text):
            name = match.group(1)
            columns = [
                col.split(":")[0].strip()
                for col in match.group(2).split(",")
                if col.strip()
            ]
            decls.setdefault(name, columns)
    return decls


def _md_escape(cell: str) -> str:
    """Escape a markdown table cell so pipes don't break the row."""
    return cell.replace("|", r"\|")


def _read_facts(tsv_path: Path) -> list[list[str]]:
    text = tsv_path.read_text(encoding="utf-8")
    return [line.split("\t") for line in text.splitlines() if line]


def _render_section(
    name: str,
    columns: list[str],
    rows: list[list[str]],
    *,
    remove_derivation: bool,
) -> str:
    """Render one predicate's facts as a markdown section."""
    if remove_derivation and columns and columns[0] == ID_COLUMN:
        # Drop the rule-provenance ``id`` column from both header and rows.
        columns = columns[1:]
        rows = [row[1:] for row in rows]

    if not columns:
        # No declaration found: fall back to placeholder column names sized
        # to the widest row.
        width = max((len(r) for r in rows), default=0)
        columns = [f"col_{i + 1}" for i in range(width)]
        logger.warning(
            "no .decl found for %r; using placeholder column names", name
        )

    lines = [f"## {name}", ""]
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in rows:
        # Pad short rows and truncate long ones to match the declared width.
        padded = (row + [""] * len(columns))[: len(columns)]
        lines.append("| " + " | ".join(_md_escape(c) for c in padded) + " |")
    lines.append("")
    return "\n".join(lines)


def project_idb(
    idb_dir: str | Path, remove_derivation: bool = False, include_only_predicates: list[str] | None = ["content", "package"]
) -> Path:
    """Write the markdown summary for ``idb_dir`` and return its path.

    By default the summary lands at
    ``<idb_dir>.parent / normalisation-summary.md`` and every ``*.tsv``
    directly in ``idb_dir`` contributes one section that includes every
    declared column.

    With ``remove_derivation=True`` the output filename gains a ``-reduced``
    suffix and the leading ``id`` column (the rule provenance trace such as
    ``R_CONTENT[F1]``) is omitted from each table.

    If ``include_only_predicates`` is ``None``, all predicates (*.tsv files) will
    be included in sorted order; otherwise, only the listed ones will be included,
    and in the order given. By default, "content" and "package" are included.
    """
    idb_dir = Path(idb_dir).resolve()
    if not idb_dir.is_dir():
        raise FileNotFoundError(f"idb directory does not exist: {idb_dir}")
    if include_only_predicates is None:
        tsv_files = sorted(idb_dir.glob("*.tsv"))
        if not tsv_files:
            raise FileNotFoundError(f"no .tsv files in: {idb_dir}")
    else:
        # If any are missing, reading from them will raise
        tsv_files = [idb_dir / f"{stem}.tsv" for stem in include_only_predicates]

    decls = _parse_decls(RULES_DIR)
    summary_filename = (
        SUMMARY_REDUCED_FILENAME if remove_derivation else SUMMARY_FILENAME
    )
    summary_path = idb_dir.parent / summary_filename

    parts = ["# Normalisation summary", ""]
    for tsv in tsv_files:
        predicate = tsv.stem
        rows = _read_facts(tsv)
        columns = decls.get(predicate, [])
        parts.append(
            _render_section(
                predicate, columns, rows, remove_derivation=remove_derivation
            )
        )

    summary_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    logger.info(
        "wrote summary with %d sections to %s", len(tsv_files), summary_path
    )
    return summary_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="project-idb",
        description=(
            "Render a markdown summary of all IDB TSV files in a folder, "
            "using column names from the rules/*.souffle declarations."
        ),
    )
    parser.add_argument(
        "idb_dir",
        metavar="IDB_DIR",
        help=(
            "path to the idb/ directory produced by inference "
            "(e.g. .souffle/<wheel-name>/<session>/idb)"
        ),
    )
    parser.add_argument(
        "--remove-derivation",
        action="store_true",
        help=(
            "drop the rule-provenance 'id' column from each table and write "
            f"to '{SUMMARY_REDUCED_FILENAME}' instead of '{SUMMARY_FILENAME}'"
        ),
    )
    parser.add_argument(
        "--include-all-predicates",
        action="store_true",
        help=(
            "include all predicates (.tsv files) in sorted order"
        ),
    )
    parser.add_argument(
        "--include-only-predicates",
        type=str,
        help=(
            "include only the comma-separated list of predicates in the order given, "
            "instead of the default of content,package"
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
    """Entry point. Prints the summary path and returns an exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    extra_kwargs = {}     # Default to using include_only_predicates="content,package"
    if args.include_all_predicates:
        extra_kwargs = {"include_only_predicates": None}
    else:
        if args.include_only_predicates:
            extra_kwargs = {"include_only_predicates": args.include_only_predicates.split(",")}

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        summary_path = project_idb(
            args.idb_dir, remove_derivation=args.remove_derivation, **extra_kwargs
        )
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1

    print(summary_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
