"""Extract a metadata EDB (extensional database) from a Python wheel.

A wheel keeps its metadata in a top-level ``*.dist-info`` directory. This
module flattens every file in that directory into a Soufflé-friendly TSV table
with the columns ``file``, ``path``, ``key`` and ``value`` and writes it to
``<base_dir>/<wheel-name>/<session>/edb/metadata-edb.tsv``. A companion file
``package-edb.tsv`` in the same directory records the package descriptor
(``name`` and ``distinfo`` keys).

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
from pathlib import Path

from packaging.metadata import parse_email

from daleq4py.wheel import WheelValidationError, validate_wheel

logger = logging.getLogger("daleq4py")

DIST_INFO_SUFFIX = ".dist-info"
EDB_FILENAME = "metadata-edb.tsv"
PACKAGE_EDB_FILENAME = "package-edb.tsv"

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
    """Turn one ``*.dist-info`` file into ``(file, path, key, value)`` rows.

    RFC 822 files (``METADATA``, ``WHEEL``) are parsed with
    :func:`packaging.metadata.parse_email`, which normalises field names,
    splits multi-value fields and folds long-description bodies into the
    ``description`` field. Unstructured files (``RECORD``, ``LICENSE``,
    ``top_level.txt``, ...) keep their raw content as a single value row with
    an empty key.
    """
    if not _looks_like_headers(text):
        # parse_email would otherwise misclassify these as a description body.
        if text.strip():
            return [(file_name, dir_path, "", text.strip())]
        return []

    raw, unparsed = parse_email(text)
    rows: list[Row] = []
    # raw: recognised core-metadata fields. Values are str, list[str] or
    # (for project_urls) dict[str, str].
    for key, value in raw.items():
        if isinstance(value, list):
            for item in value:
                rows.append((file_name, dir_path, key, str(item)))
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                rows.append(
                    (file_name, dir_path, f"{key}.{sub_key}", str(sub_value))
                )
        else:
            rows.append((file_name, dir_path, key, str(value)))
    # unparsed: any remaining fields (e.g. everything in WHEEL). Always list[str].
    for key, values in unparsed.items():
        for item in values:
            rows.append((file_name, dir_path, key, item))
    return rows


def _write_tsv(path: Path, rows) -> None:
    """Write ``rows`` (any iterable of string tuples) as escaped TSV."""
    with path.open("w", encoding="utf-8", newline="\n") as out:
        for row in rows:
            out.write("\t".join(_escape(field) for field in row) + "\n")


def extract_edb(
    wheel: str | Path, base_dir: str | Path = DEFAULT_BASE_DIR
) -> Path:
    """Extract the metadata EDB from ``wheel`` and return the metadata TSV path.

    Two files are written to
    ``<base_dir>/<wheel-name>/<session>/edb/``:

    * ``metadata-edb.tsv`` -- ``(file, path, key, value)`` rows extracted from
      every file in the wheel's ``*.dist-info`` directory.
    * ``package-edb.tsv`` -- ``(key, value)`` descriptor with two rows:
      ``name`` (the package's ``<name>-<version>`` token, taken from the
      dist-info directory) and ``distinfo`` (the dist-info directory name).

    ``<wheel-name>`` is the wheel filename without its ``.whl`` suffix and
    ``<session>`` is a freshly generated id. A relative ``base_dir`` is
    resolved against the project root, not the current working directory. The
    returned :class:`~pathlib.Path` is the ``metadata-edb.tsv`` file; the
    package descriptor sits alongside it in the same directory.
    """
    wheel_path = validate_wheel(str(wheel))
    wheel_name = wheel_path.stem

    rows: list[Row] = []
    dist_info_dirs: set[str] = set()
    with zipfile.ZipFile(wheel_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/")
            if not parts[0].endswith(DIST_INFO_SUFFIX):
                continue  # only the .dist-info directory holds metadata
            dist_info_dirs.add(parts[0])
            file_name = parts[-1]
            dir_path = "/".join(parts[:-1])
            text = archive.read(info.filename).decode("utf-8", errors="replace")
            rows.extend(_rows_for_member(file_name, dir_path, text))

    if len(dist_info_dirs) != 1:
        raise WheelValidationError(
            f"wheel does not contain exactly one .dist-info directory: "
            f"{sorted(dist_info_dirs) or 'none'}"
        )
    [dist_info_dir] = dist_info_dirs
    package_name = dist_info_dir[: -len(DIST_INFO_SUFFIX)]

    base = Path(base_dir)
    if not base.is_absolute():
        base = PROJECT_ROOT / base

    session = _new_session()
    edb_dir = base / wheel_name / session / "edb"
    edb_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = edb_dir / EDB_FILENAME
    _write_tsv(metadata_path, rows)

    package_path = edb_dir / PACKAGE_EDB_FILENAME
    _write_tsv(package_path, [("name", package_name), ("distinfo", dist_info_dir)])

    logger.info("extracted %d metadata rows to %s", len(rows), metadata_path)
    logger.info("wrote package descriptor to %s", package_path)
    return metadata_path


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
