# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Extract a content EDB (extensional database) from a Python wheel.

This module walks **every** member of the wheel zip and flattens each into a
Soufflé-friendly TSV table with the columns ``id``, ``file``, ``path``,
``key`` and ``value``. The result is written to
``<base_dir>/<wheel-name>/<session>/edb/content.tsv``. A companion file
``package.tsv`` in the same directory records the package descriptor with
columns ``id``, ``key``, ``value`` (two rows: ``name`` and ``distinfo``).

The ``id`` column carries a unique fact id (``F1``, ``F2``, ...) assigned in
extraction order. The counter runs across both files so every fact in one
EDB is uniquely identified.

For each wheel member, two kinds of facts are emitted:

* **Explicit keys** -- only for the recognised metadata files inside
  ``*.dist-info/``:

  * ``METADATA`` and ``WHEEL`` are parsed as RFC 822 header blocks (using
    :func:`packaging.metadata.parse_email`), and contribute one row per
    ``Key: value`` pair (with field names normalised by ``parse_email``,
    e.g. ``Requires-Dist`` -> ``requires_dist``). Each ``requires_dist``
    value additionally contributes a second row under the synthetic key
    ``@norm/requires_dist`` whose value is the PEP 508 normalised
    requirement (see :func:`_normalise_requirement`), so cosmetic build
    differences in dependency specifiers do not register as a mismatch.
  * ``RECORD`` is comma-separated and contributes one row per packaged file:
    the first comma-separated token (the packaged file path) is the key and
    the rest of the line (typically ``sha256=<digest>,<size>``) is the value.

  Other files (``LICENSE``, ``top_level.txt``, ``entry_points.txt``, any
  ``.py`` source, any resource) contribute no explicit rows -- their content
  is captured by the synthetic keys below.

The ``@`` prefix is reserved for the synthetic keys below: every key this
extractor generates starts with ``@``, and any explicit (package-controlled)
key that also starts with ``@`` is escaped with a leading ``_`` (see
:func:`_sanitise_explicit_key`) so a crafted wheel cannot forge a fact that
collides with a genuine synthetic one.

* **Synthetic keys** -- for every member, regardless of location or type:

  * ``@sha256`` -- SHA-256 of the raw (uncompressed) archive bytes.
  * ``@norm/sha256`` -- SHA-256 after normalisation, emitted only for text
    files (heuristic: no NUL byte in the first 8 KiB). For ``.py`` files the
    normaliser is :func:`daleq4py.normalise_pysrc.normalise_source` (AST
    round-trip; strips comments and canonicalises layout); for other text
    files it is a pure LF normalisation of line endings.
  * ``@src-exists`` -- ``true``/``false``; whether a member with the same
    archive-relative path exists in the optional ``src`` baseline.
  * ``@src-exists-moved`` -- ``true``/``false``; whether a member with the
    same basename exists at any path in ``src``.
  * ``@src/sha256``, ``@src/norm/sha256`` -- SHA-256 (raw / normalised) of
    the matched src file. Emitted only when at least one of the two
    ``@src-exists*`` keys is true. The match preference is path-equality
    first, then the alphabetically-first basename match. ``@src/norm/sha256``
    follows the same text-only rule as ``@norm/sha256``.

  The four ``@src-*`` keys are omitted entirely when ``src`` is not supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
import time
import zipfile
from itertools import count
from pathlib import Path

from packaging.metadata import parse_email
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from daleq4py.normalise_pysrc import normalise_source
from daleq4py.wheel import WheelValidationError, validate_wheel

logger = logging.getLogger("daleq4py")

DIST_INFO_SUFFIX = ".dist-info"
EDB_FILENAME = "content.tsv"
PACKAGE_EDB_FILENAME = "package.tsv"
IDB_REMOVE_CONTENT_FILENAME = "remove_content.tsv"
RECORD_FILENAME = "RECORD"

# Synthetic-key constants (also re-exported for tests / downstream callers).
KEY_SHA256 = "@sha256"
KEY_NORM_SHA256 = "@norm/sha256"

# Core-metadata key (as emitted by packaging's RawMetadata) whose values carry
# PEP 508 dependency specifiers, plus the synthetic key under which the
# normalised form of each value is additionally emitted.
REQUIRES_DIST_KEY = "requires_dist"
KEY_NORM_REQUIRES_DIST = "@norm/requires_dist"

# The synthetic key namespace is reserved: every key this extractor generates
# begins with ``@``. Explicit (package-controlled) keys must never enter that
# namespace, otherwise a crafted wheel could forge a fact that collides with a
# genuine synthetic one. Any explicit key starting with the reserved prefix is
# escaped by prepending the sentinel below, keeping the invariant "a leading
# ``@`` means extractor-generated".
SYNTHETIC_KEY_PREFIX = "@"
ESCAPED_EXPLICIT_KEY_PREFIX = "_"
KEY_SRC_EXISTS = "@src-exists"
KEY_SRC_EXISTS_MOVED = "@src-exists-moved"
KEY_SRC_SHA256 = "@src/sha256"
KEY_SRC_NORM_SHA256 = "@src/norm/sha256"

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

# Heuristic threshold for treating bytes as text: no NUL byte in this many
# leading bytes. Same rule as :mod:`daleq4py.wheel_diff`.
_TEXT_SNIFF_BYTES = 8192

PY_SUFFIX = ".py"

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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_text(data: bytes) -> bool:
    """Heuristic: text if no NUL byte appears in the first 8 KiB."""
    return b"\x00" not in data[:_TEXT_SNIFF_BYTES]


def _lf_normalise(data: bytes) -> bytes:
    """Decode as UTF-8 (lossy), collapse CRLF/CR to LF, re-encode."""
    return (
        data.decode("utf-8", errors="replace")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .encode("utf-8")
    )


def _normalise_for_hash(file_name: str, data: bytes) -> bytes:
    """Return the byte form to feed into :func:`_sha256` for ``@norm/sha256``.

    For ``.py`` files: AST round-trip via ``normalise_source`` (drops
    comments, canonicalises layout, output is already LF-terminated). If the
    source won't parse, fall back to pure LF normalisation so we still emit
    a stable hash.
    For other text files: pure LF normalisation.
    """
    if file_name.endswith(PY_SUFFIX):
        try:
            return normalise_source(
                data.decode("utf-8", errors="replace")
            ).encode("utf-8")
        except SyntaxError:
            return _lf_normalise(data)
    return _lf_normalise(data)


def _normalise_requirement(value: str) -> str:
    """Return the PEP 508 normalised form of a ``Requires-Dist`` value.

    Collapses the cosmetic differences build tools introduce -- whitespace
    around ``;`` and operators, marker quote style, legacy parenthesised
    versions, specifier ordering -- and canonicalises the distribution name
    (PEP 503). A value that cannot be parsed as a requirement is returned
    unchanged, mirroring the lenient fallback used for source normalisation.
    """
    try:
        req = Requirement(value)
    except InvalidRequirement:
        return value
    req.name = canonicalize_name(req.name)
    return str(req)


def _load_src_index(
    src: str | Path,
) -> tuple[Path, dict[str, bytes], dict[str, list[str]]]:
    """Validate ``src`` (a wheel/zip) and return (path, by-path, by-basename).

    ``by_basename`` lists every src path sharing each basename, sorted, so
    callers can pick the alphabetically-first match deterministically.
    """
    candidate = Path(src).expanduser()
    if not candidate.is_file():
        raise WheelValidationError(f"src is not a file: {src}")
    if not zipfile.is_zipfile(candidate):
        raise WheelValidationError(f"src is not a valid zip: {src}")
    src_path = candidate.resolve()
    by_path: dict[str, bytes] = {}
    by_basename: dict[str, list[str]] = {}
    with zipfile.ZipFile(src_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            data = archive.read(info.filename)
            by_path[info.filename] = data
            basename = info.filename.rsplit("/", 1)[-1]
            by_basename.setdefault(basename, []).append(info.filename)
    for paths in by_basename.values():
        paths.sort()
    return src_path, by_path, by_basename


def _sanitise_explicit_key(key: str, file_name: str, dir_path: str) -> str:
    """Keep package-derived keys out of the reserved synthetic namespace.

    Synthetic keys are emitted by this extractor and always start with
    :data:`SYNTHETIC_KEY_PREFIX` (``@``). A wheel could declare a metadata
    field or ``RECORD`` entry whose key also starts with ``@`` (e.g.
    ``@sha256``), producing an explicit fact that collides with a genuine
    synthetic one. Such a key is escaped by prepending
    :data:`ESCAPED_EXPLICIT_KEY_PREFIX` so it can never enter the ``@``
    namespace; the rewrite is logged at WARNING. Keys that don't intrude are
    returned unchanged (the common case has no cost beyond a prefix check).
    """
    if not key.startswith(SYNTHETIC_KEY_PREFIX):
        return key
    escaped = f"{ESCAPED_EXPLICIT_KEY_PREFIX}{key}"
    logger.warning(
        "escaped reserved explicit key %r -> %r in %s/%s",
        key, escaped, dir_path, file_name,
    )
    return escaped


def _rows_for_record(file_name: str, dir_path: str, text: str) -> list[Row]:
    """Turn ``RECORD`` (comma-separated, one line per packaged file) into rows.

    Each non-blank line becomes one row: the first comma-separated token (the
    packaged file path) is the key and the remainder of the line (typically
    ``sha256=<digest>,<size>``) is the value.
    """
    rows: list[Row] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(",")
        rows.append((
            file_name, dir_path,
            _sanitise_explicit_key(key, file_name, dir_path),
            value,
        ))
    return rows


def _explicit_rows(file_name: str, dir_path: str, data: bytes) -> list[Row]:
    """Return the explicit key-value rows for a wheel member, or [].

    Only the recognised metadata files contribute explicit rows: ``RECORD``
    (per-line) and any RFC 822 file with a ``Key: value`` header block
    (``METADATA``, ``WHEEL``). All other members produce only synthetic rows.
    """
    if file_name == RECORD_FILENAME:
        return _rows_for_record(
            file_name, dir_path, data.decode("utf-8", errors="replace")
        )

    text = data.decode("utf-8", errors="replace")
    if not (dir_path.endswith(".dist-info") and file_name in ("METADATA", "WHEEL")):
        return []

    raw, unparsed = parse_email(text)
    rows: list[Row] = []
    # raw: recognised core-metadata fields. Values are str, list[str] or
    # (for project_urls) dict[str, str].
    for key, value in raw.items():
        safe_key = _sanitise_explicit_key(key, file_name, dir_path)
        if isinstance(value, list):
            for item in value:
                item_str = str(item)
                rows.append((file_name, dir_path, safe_key, item_str))
                # For dependency specifiers, additionally emit the normalised
                # value under our own (already trusted) synthetic key.
                if key == REQUIRES_DIST_KEY:
                    rows.append((
                        file_name, dir_path,
                        KEY_NORM_REQUIRES_DIST,
                        _normalise_requirement(item_str),
                    ))
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                rows.append((
                    file_name, dir_path,
                    _sanitise_explicit_key(
                        f"{key}.{sub_key}", file_name, dir_path
                    ),
                    str(sub_value),
                ))
        else:
            rows.append((file_name, dir_path, safe_key, str(value)))
    # unparsed: any remaining fields (e.g. everything in WHEEL). Always list[str].
    for key, values in unparsed.items():
        safe_key = _sanitise_explicit_key(key, file_name, dir_path)
        for item in values:
            rows.append((file_name, dir_path, safe_key, item))
    return rows


def _synthetic_rows(
    file_name: str,
    dir_path: str,
    data: bytes,
    *,
    src_by_path: dict[str, bytes] | None,
    src_by_basename: dict[str, list[str]] | None,
) -> list[Row]:
    """Return the synthetic key rows for one wheel member.

    ``src_by_path`` / ``src_by_basename`` are ``None`` when no ``src`` was
    supplied -- in that case the four ``@src-*`` rows are omitted.
    """
    rows: list[Row] = []
    full_path = f"{dir_path}/{file_name}" if dir_path else file_name
    text_like = _is_text(data)

    # @sha256 -- always.
    rows.append((file_name, dir_path, KEY_SHA256, _sha256(data)))

    # @norm/sha256 -- only when the bytes look like text.
    if text_like:
        rows.append((
            file_name, dir_path,
            KEY_NORM_SHA256,
            _sha256(_normalise_for_hash(file_name, data)),
        ))

    # @src-* -- only when a src baseline is supplied.
    if src_by_path is not None and src_by_basename is not None:
        path_match: bytes | None = src_by_path.get(full_path)
        basename_matches: list[str] = src_by_basename.get(file_name, [])
        path_exists = path_match is not None
        moved_exists = bool(basename_matches)

        rows.append((
            file_name, dir_path,
            KEY_SRC_EXISTS,
            "true" if path_exists else "false",
        ))
        rows.append((
            file_name, dir_path,
            KEY_SRC_EXISTS_MOVED,
            "true" if moved_exists else "false",
        ))

        # Pick the matched src file: prefer same-path; otherwise the
        # alphabetically-first basename match.
        matched_bytes: bytes | None = None
        if path_exists:
            matched_bytes = path_match
        elif basename_matches:
            matched_bytes = src_by_path[basename_matches[0]]

        if matched_bytes is not None:
            rows.append((
                file_name, dir_path,
                KEY_SRC_SHA256,
                _sha256(matched_bytes),
            ))
            if _is_text(matched_bytes):
                rows.append((
                    file_name, dir_path,
                    KEY_SRC_NORM_SHA256,
                    _sha256(_normalise_for_hash(file_name, matched_bytes)),
                ))

    return rows


def _write_tsv(path: Path, rows) -> None:
    """Write ``rows`` (any iterable of string tuples) as escaped TSV."""
    with path.open("w", encoding="utf-8", newline="\n") as out:
        for row in rows:
            out.write("\t".join(_escape(field) for field in row) + "\n")


def extract_edb(
    wheel: str | Path,
    base_dir: str | Path = DEFAULT_BASE_DIR,
    src: str | Path | None = None,
) -> Path:
    """Extract the content EDB from ``wheel`` and return the content TSV path.

    Two files are written to ``<base_dir>/<wheel-name>/<session>/edb/``:

    * ``content.tsv`` -- ``(id, file, path, key, value)`` rows extracted from
      **every** member of the wheel. See the module docstring for the
      explicit / synthetic key catalogue.
    * ``package.tsv`` -- ``(id, key, value)`` descriptor with two rows:
      ``name`` (the package's ``<name>-<version>`` token, taken from the
      dist-info directory) and ``distinfo`` (the dist-info directory name).

    The ``id`` column is a unique counter (``F1``, ``F2``, ...) shared across
    both files, so every fact in one EDB has a distinct identifier.

    ``<wheel-name>`` is the wheel filename without its ``.whl`` suffix and
    ``<session>`` is a freshly generated id. A relative ``base_dir`` is
    resolved against the project root, not the current working directory. The
    returned :class:`~pathlib.Path` is the ``content.tsv`` file; the package
    descriptor sits alongside it in the same directory.

    ``src`` is an optional "trusted" wheel/zip whose ``.py`` (and other)
    members define a baseline used to populate the ``@src-*`` synthetic keys.
    When ``src`` is ``None`` those keys are omitted entirely.
    """
    wheel_path = validate_wheel(str(wheel))
    wheel_name = wheel_path.stem

    src_path: Path | None = None
    src_by_path: dict[str, bytes] | None = None
    src_by_basename: dict[str, list[str]] | None = None
    if src is not None:
        src_path, src_by_path, src_by_basename = _load_src_index(src)
        logger.info(
            "src baseline: %s (%d member(s))", src_path, len(src_by_path)
        )

    rows: list[Row] = []
    dist_info_dirs: set[str] = set()
    with zipfile.ZipFile(wheel_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/")
            file_name = parts[-1]
            dir_path = "/".join(parts[:-1])

            if parts[0].endswith(DIST_INFO_SUFFIX):
                dist_info_dirs.add(parts[0])

            data = archive.read(info.filename)

            # Explicit rows first (only for recognised metadata files), then
            # the synthetic rows for this member. Keeping them contiguous in
            # the TSV makes the EDB easier to inspect by eye.
            rows.extend(_explicit_rows(file_name, dir_path, data))
            rows.extend(_synthetic_rows(
                file_name, dir_path, data,
                src_by_path=src_by_path,
                src_by_basename=src_by_basename,
            ))

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

    # Unique fact ids "F1", "F2", ... shared across both files.
    fact_ids = (f"F{n}" for n in count(1))

    content_path = edb_dir / EDB_FILENAME
    _write_tsv(content_path, [(next(fact_ids), *row) for row in rows])

    package_path = edb_dir / PACKAGE_EDB_FILENAME
    _write_tsv(
        package_path,
        [
            (next(fact_ids), "name", package_name),
            (next(fact_ids), "distinfo", dist_info_dir),
        ],
    )

    logger.info("extracted %d content rows to %s", len(rows), content_path)
    logger.info("wrote package descriptor to %s", package_path)
    return content_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extract-edb",
        description=(
            "Extract a content EDB (TSV) from a Python wheel; covers every "
            "member of the wheel, emitting explicit rows for recognised "
            "metadata files and synthetic rows (sha256, normalised sha256, "
            "size, optional src-baseline cross-references) for every file."
        ),
    )
    parser.add_argument(
        "wheel",
        metavar="WHEEL",
        help="path to the Python wheel (.whl) to extract content from",
    )
    parser.add_argument(
        "--src",
        metavar="ZIP",
        default=None,
        help=(
            "optional 'trusted' wheel/zip whose members define the baseline "
            "for the @src-* synthetic keys; when omitted, no @src-* facts "
            "are emitted"
        ),
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
        edb_path = extract_edb(args.wheel, args.base_dir, src=args.src)
    except WheelValidationError as exc:
        logger.error("invalid wheel: %s", exc)
        return 1

    print(edb_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
