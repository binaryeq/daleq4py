# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Normalise Python source files for binary-equivalence analysis.

Strategy: round-trip through the stdlib AST (``ast.parse`` + ``ast.unparse``).
This is a high-accuracy approach that:

* removes ``#`` comments (the AST does not preserve them);
* standardises layout to a canonical, deterministic form produced by ``ast.unparse``;
* always writes ``\\n`` line endings.

Docstrings are preserved: syntactically they are string-literal expressions,
not comments, so the AST keeps them.
"""

from __future__ import annotations

import argparse
import ast
import logging
import sys
from pathlib import Path

logger = logging.getLogger("daleq4py.normalise_pysrc")


def normalise_source(source: str | bytes) -> str:
    """Round-trip source through the AST and return canonical Python source.

    Pass original bytes when reading files so Python applies PEP 263 encoding
    declarations and UTF-8 BOM handling before parsing. A string is treated as
    already decoded source. Invalid source or encodings raise ``SyntaxError``.
    """
    tree = ast.parse(source)
    out = ast.unparse(tree)
    if not out.endswith("\n"):
        out += "\n"
    return out


def _iter_py_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _resolve_output_path(src_file: Path, input_root: Path, output_dir: Path) -> Path:
    if input_root.is_file():
        return output_dir / input_root.name
    rel = src_file.relative_to(input_root)
    return output_dir / input_root.name / rel


def _process_one(src_file: Path, dest: Path) -> bool:
    try:
        source = src_file.read_bytes()
    except OSError:
        logger.error("cannot read %s", src_file, exc_info=True)
        return False
    try:
        normalised = normalise_source(source)
    except SyntaxError:
        logger.error("syntax error in %s", src_file, exc_info=True)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="\n") as f:
        f.write(normalised)
    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="normalise-pysrc",
        description=(
            "Normalise Python source files: strip comments, standardise newlines "
            "to '\\n', and emit a canonical layout. Uses the stdlib ast.parse + "
            "ast.unparse round-trip for high accuracy."
        ),
    )
    parser.add_argument(
        "paths",
        metavar="PATH",
        nargs="+",
        type=Path,
        help="one or more Python source files or directories (recursed for *.py)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="DIR",
        help="write normalised files under this directory, mirroring the input tree",
    )
    mode.add_argument(
        "-i",
        "--in-place",
        action="store_true",
        help="overwrite source files in place",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable verbose (debug) logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    total = 0
    failed = 0
    for root in args.paths:
        if not root.exists():
            logger.error("path does not exist: %s", root)
            failed += 1
            continue
        files = _iter_py_files(root)
        logger.info("normalising %d file(s) under %s", len(files), root)
        for src in files:
            dest = src if args.in_place else _resolve_output_path(src, root, args.output)
            total += 1
            if not _process_one(src, dest):
                failed += 1

    logger.info("done: %d processed, %d failed", total, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
