# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Run Soufflé inference on a wheel's extracted EDB.

Given the ``<session>/edb/`` directory produced by :mod:`daleq4py.extract_edb`, this
module:

1. concatenates every ``rules/*.souffle`` file (in sorted order) into
   ``<session>/mergedEDBAndRules.souffle``, prefixing each file's content with
   a ``// from <path-relative-to-project-root>`` provenance comment;
2. replaces the four ``<*-facts>`` placeholders in that merged file with
   absolute paths to the EDB (input) and IDB (output) fact files;
3. creates the sibling ``<session>/idb/`` directory;
4. invokes the ``souffle`` binary on the merged file, which writes the inferred IDB
   (as *.tsv file) into the IDB directory.

The function returns the IDB directory path.

"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from daleq4py.extract_edb import (
    EDB_FILENAME,
    PACKAGE_EDB_FILENAME,
    PROJECT_ROOT,
)

logger = logging.getLogger("daleq4py")

RULES_DIR = PROJECT_ROOT / "rules"
MERGED_FILENAME = "mergedEDBAndRules.souffle"
SOUFFLE_EXECUTABLE = "souffle"

# Placeholders inside the merged rules file that get substituted with
# absolute paths before souffle is invoked.
_EDB_METADATA_PLACEHOLDER = "<edb-metadata-facts>"
_EDB_PACKAGE_PLACEHOLDER = "<edb-package-facts>"
_IDB_METADATA_PLACEHOLDER = "<idb-metadata-facts>"
_IDB_PACKAGE_PLACEHOLDER = "<idb-package-facts>"


class InferenceError(RuntimeError):
    """Raised when inference can't be run (bad inputs or souffle failure)."""


def run_inference(edb_dir: str | Path) -> Path:
    """Run souffle inference on ``edb_dir`` and return the IDB directory.

    ``edb_dir`` must be an ``edb/`` directory holding the two TSVs produced
    by :func:`daleq4py.extract_edb.extract_edb` (``metadata.tsv`` and
    ``package.tsv``). The merged Soufflé file and the ``idb/`` directory are
    written next to it inside the same session directory.
    """
    edb_dir = Path(edb_dir).resolve()
    if not edb_dir.is_dir():
        raise InferenceError(f"edb directory does not exist: {edb_dir}")
    if edb_dir.name != "edb":
        raise InferenceError(
            f"expected an 'edb' directory, got: {edb_dir.name!r}"
        )

    metadata_edb = edb_dir / EDB_FILENAME
    package_edb = edb_dir / PACKAGE_EDB_FILENAME
    for required in (metadata_edb, package_edb):
        if not required.exists():
            raise InferenceError(f"missing fact file: {required}")

    rule_files = sorted(RULES_DIR.glob("*.souffle"))
    if not rule_files:
        raise InferenceError(f"no .souffle files in: {RULES_DIR}")

    session_dir = edb_dir.parent
    idb_dir = session_dir / "idb"
    idb_dir.mkdir(parents=True, exist_ok=True)

    metadata_idb = idb_dir / EDB_FILENAME
    package_idb = idb_dir / PACKAGE_EDB_FILENAME

    # Substitute paths relative to ``session_dir`` (rather than absolute) so
    # the merged file stays portable within the session tree. Souffle is then
    # invoked with ``session_dir`` as its working directory.
    def _rel(p: Path) -> str:
        return p.relative_to(session_dir).as_posix()

    # Concatenate every rules file, prefixing each block with a provenance
    # comment so the merged file points back to the source of each rule.
    merged_chunks: list[str] = []
    for rule_file in rule_files:
        provenance = rule_file.relative_to(PROJECT_ROOT).as_posix()
        body = rule_file.read_text(encoding="utf-8")
        if not body.endswith("\n"):
            body += "\n"
        merged_chunks.append(f"// from {provenance}\n{body}\n")

    merged_path = session_dir / MERGED_FILENAME
    rule_text = (
        "".join(merged_chunks)
        .replace(_EDB_METADATA_PLACEHOLDER, _rel(metadata_edb))
        .replace(_EDB_PACKAGE_PLACEHOLDER, _rel(package_edb))
        .replace(_IDB_METADATA_PLACEHOLDER, _rel(metadata_idb))
        .replace(_IDB_PACKAGE_PLACEHOLDER, _rel(package_idb))
    )
    merged_path.write_text(rule_text, encoding="utf-8")
    logger.info(
        "wrote merged souffle program (%d rule file(s)) to %s",
        len(rule_files), merged_path,
    )

    if shutil.which(SOUFFLE_EXECUTABLE) is None:
        raise InferenceError(
            f"{SOUFFLE_EXECUTABLE!r} executable not found on PATH"
        )

    logger.info("running souffle on %s (cwd=%s)", MERGED_FILENAME, session_dir)
    completed = subprocess.run(  # noqa: S603 - args are explicit, not shell
        [SOUFFLE_EXECUTABLE, MERGED_FILENAME],
        cwd=str(session_dir),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        logger.error("souffle stderr:\n%s", completed.stderr)
        raise InferenceError(
            f"souffle exited with status {completed.returncode}"
        )
    if completed.stderr.strip():
        logger.debug("souffle stderr:\n%s", completed.stderr)

    logger.info("idb facts written to %s", idb_dir)
    return idb_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inference",
        description=(
            "Run souffle inference on a wheel's extracted EDB facts and "
            "produce the IDB facts in a sibling idb/ directory."
        ),
    )
    parser.add_argument(
        "edb_dir",
        metavar="EDB_DIR",
        help=(
            "path to the edb/ directory produced by extract-edb "
            "(e.g. .souffle/<wheel-name>/<session>/edb)"
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
    """Entry point. Prints the IDB directory path and returns an exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        idb_dir = run_inference(args.edb_dir)
    except InferenceError as exc:
        logger.error("%s", exc)
        return 1

    print(idb_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
