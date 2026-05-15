"""Extract a metadata EDB (extensional database) from a Python wheel.

A wheel keeps its metadata in a top-level ``*.dist-info`` directory. This
module flattens every file in that directory into a Soufflé-friendly TSV table
with the columns ``file``, ``path``, ``key`` and ``value`` and writes it to
``<base_dir>/<wheel-name>/<session>/edb/metadata-edb.tsv``.

Files with an RFC 822 style ``Key: value`` header block (``METADATA``,
``WHEEL``) contribute one row per pair. Files without that structure
(``LICENSE``, ``AUTHORS``, ``RECORD``, ...) contribute a single row whose key
is the empty string and whose value is the file's raw content.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
import zipfile
from email.parser import Parser
from pathlib import Path

from daleq4py.wheel import WheelValidationError, validate_wheel

logger = logging.getLogger("daleq4py")

DIST_INFO_SUFFIX = ".dist-info"
EDB_FILENAME = "metadata-edb.tsv"

# Project root: <root>/src/daleq4py/extract_edb.py -> parents[2]. A relative
# base directory is resolved against this so EDB files land inside the project
# regardless of the current working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_DIR = ".souffle"

# Session ids sort newest-first: a wide constant minus a nanosecond timestamp.
# 1e19 comfortably exceeds any current time.time_ns() value (~1.8e18), so the
# difference stays positive and 19 digits wide for centuries.
_SESSION_REFERENCE = 10**19

# First meaningful line of an RFC 822 header block: "Token:" or "Token: value".
_HEADER_LINE = re.compile(r"[^:\s][^:]*:(\s|$)")

# (file, path, key, value)
Row = tuple[str, str, str, str]


def _new_session() -> str:
    """Return a unique, reverse-chronological session id."""
    return f"{_SESSION_REFERENCE - time.time_ns():019d}"


def _escape(field: str) -> str:
    """Escape a field so it stays on a single tab-separated line."""
    return (
        field.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def _looks_like_headers(text: str) -> bool:
    """True if ``text`` opens with an RFC 822 style ``Key: value`` block."""
    for line in text.splitlines():
        if not line.strip():
            continue  # tolerate leading blank lines
        return bool(_HEADER_LINE.match(line))  # first real line decides
    return False


def _rows_for_member(file_name: str, dir_path: str, text: str) -> list[Row]:
    """Turn one ``*.dist-info`` file into ``(file, path, key, value)`` rows."""
    if _looks_like_headers(text):
        message = Parser().parsestr(text)
        rows: list[Row] = [
            (file_name, dir_path, key, value) for key, value in message.items()
        ]
        body = message.get_payload()
        if isinstance(body, str) and body.strip():
            # e.g. the long description trailing the METADATA headers
            rows.append((file_name, dir_path, "", body.strip()))
        return rows

    # No key-value structure (LICENSE, AUTHORS, RECORD, ...): keep raw content.
    if text.strip():
        return [(file_name, dir_path, "", text.strip())]
    return []


def extract_edb(
    wheel: str | Path, base_dir: str | Path = DEFAULT_BASE_DIR
) -> Path:
    """Extract the metadata EDB from ``wheel`` and return the written TSV path.

    The table is written to
    ``<base_dir>/<wheel-name>/<session>/edb/metadata-edb.tsv``, where
    ``<wheel-name>`` is the wheel filename without its ``.whl`` suffix and
    ``<session>`` is a freshly generated id. A relative ``base_dir`` is
    resolved against the project root, not the current working directory.
    """
    wheel_path = validate_wheel(str(wheel))
    wheel_name = wheel_path.stem

    rows: list[Row] = []
    with zipfile.ZipFile(wheel_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/")
            if not parts[0].endswith(DIST_INFO_SUFFIX):
                continue  # only the .dist-info directory holds metadata
            file_name = parts[-1]
            dir_path = "/".join(parts[:-1])
            text = archive.read(info.filename).decode("utf-8", errors="replace")
            rows.extend(_rows_for_member(file_name, dir_path, text))

    base = Path(base_dir)
    if not base.is_absolute():
        base = PROJECT_ROOT / base

    session = _new_session()
    edb_dir = base / wheel_name / session / "edb"
    edb_dir.mkdir(parents=True, exist_ok=True)
    edb_path = edb_dir / EDB_FILENAME

    with edb_path.open("w", encoding="utf-8", newline="\n") as out:
        for row in rows:
            out.write("\t".join(_escape(field) for field in row) + "\n")

    logger.info("extracted %d metadata rows to %s", len(rows), edb_path)
    return edb_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extract-edb",
        description=(
            "Extract a metadata EDB (TSV) from a Python wheel's .dist-info "
            "directory."
        ),
    )
    parser.add_argument(
        "wheel",
        metavar="WHEEL",
        help="path to the Python wheel (.whl) to extract metadata from",
    )
    parser.add_argument(
        "--base-dir",
        default=DEFAULT_BASE_DIR,
        metavar="DIR",
        help=(
            "root directory for the EDB tree; a relative path is resolved "
            f"against the project root (default: {DEFAULT_BASE_DIR})"
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
    """Entry point. Prints the generated TSV path and returns an exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        edb_path = extract_edb(args.wheel, args.base_dir)
    except WheelValidationError as exc:
        logger.error("invalid wheel: %s", exc)
        return 1

    print(edb_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
