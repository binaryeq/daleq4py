# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code
# Adapted from https://github.com/binaryeq/pyeqpkg (diff-script/wheel-diff.py).

"""Diff two Python wheel files and produce a markdown report.

For every member of either wheel the report records, in order:

* the two wheel paths;
* files present only in wheel 1, with SHA-256;
* files present only in wheel 2, with SHA-256;
* files present in both wheels with byte-identical content, with SHA-256;
* files present in both wheels with differing content -- each with both
  SHA-256 digests, and a unified textual diff (when both sides decode as
  text) or a ``*Binary files differ.*`` note otherwise.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import logging
import sys
import zipfile
from pathlib import Path

from daleq4py.wheel import WheelValidationError, validate_wheel

logger = logging.getLogger("daleq4py.wheel_diff")

# Treat a file as text if no NUL byte appears in the first 8 KiB.
_TEXT_SNIFF_BYTES = 8192


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_text(data: bytes) -> bool:
    return b"\x00" not in data[:_TEXT_SNIFF_BYTES]


def _read_wheel(path: Path) -> dict[str, bytes]:
    """Return a mapping of archive-relative paths to raw bytes."""
    contents: dict[str, bytes] = {}
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            if not info.is_dir():
                contents[info.filename] = zf.read(info.filename)
    return contents


def build_report(wheel1: str | Path, wheel2: str | Path) -> str:
    """Build and return the markdown diff report for two wheels."""
    w1 = _read_wheel(Path(wheel1))
    w2 = _read_wheel(Path(wheel2))

    names1 = set(w1)
    names2 = set(w2)
    only_in_1 = sorted(names1 - names2)
    only_in_2 = sorted(names2 - names1)
    in_both = sorted(names1 & names2)

    identical: list[tuple[str, str]] = []
    changed: list[str] = []
    for name in in_both:
        h1 = _sha256_of_bytes(w1[name])
        h2 = _sha256_of_bytes(w2[name])
        if h1 == h2:
            identical.append((name, h1))
        else:
            changed.append(name)

    lines: list[str] = []

    # Header
    lines.append("# Wheel Diff Report\n")
    lines.append("| | File |")
    lines.append("|---|---|")
    lines.append(f"| **Wheel 1** | `{wheel1}` |")
    lines.append(f"| **Wheel 2** | `{wheel2}` |")
    lines.append("")

    # Only in wheel 1
    lines.append(f"## Files only in Wheel 1 ({len(only_in_1)})\n")
    if only_in_1:
        lines.append("| File | SHA-256 |")
        lines.append("|---|---|")
        for name in only_in_1:
            lines.append(f"| `{name}` | `{_sha256_of_bytes(w1[name])}` |")
    else:
        lines.append("*(none)*")
    lines.append("")

    # Only in wheel 2
    lines.append(f"## Files only in Wheel 2 ({len(only_in_2)})\n")
    if only_in_2:
        lines.append("| File | SHA-256 |")
        lines.append("|---|---|")
        for name in only_in_2:
            lines.append(f"| `{name}` | `{_sha256_of_bytes(w2[name])}` |")
    else:
        lines.append("*(none)*")
    lines.append("")

    # Identical
    lines.append(f"## Identical files in both wheels ({len(identical)})\n")
    if identical:
        lines.append("| File | SHA-256 |")
        lines.append("|---|---|")
        for name, h in identical:
            lines.append(f"| `{name}` | `{h}` |")
    else:
        lines.append("*(none)*")
    lines.append("")

    # Non-identical
    lines.append(f"## Non-identical files in both wheels ({len(changed)})\n")
    if not changed:
        lines.append("*(none)*")
        lines.append("")

    for name in changed:
        data1 = w1[name]
        data2 = w2[name]
        h1 = _sha256_of_bytes(data1)
        h2 = _sha256_of_bytes(data2)

        lines.append(f"### `{name}`\n")
        lines.append("| | SHA-256 |")
        lines.append("|---|---|")
        lines.append(f"| **Wheel 1** | `{h1}` |")
        lines.append(f"| **Wheel 2** | `{h2}` |")
        lines.append("")

        if _is_text(data1) and _is_text(data2):
            text1 = data1.decode("utf-8", errors="replace").splitlines(keepends=True)
            text2 = data2.decode("utf-8", errors="replace").splitlines(keepends=True)
            diff = list(
                difflib.unified_diff(
                    text1,
                    text2,
                    fromfile=f"wheel1/{name}",
                    tofile=f"wheel2/{name}",
                )
            )
            if diff:
                lines.append("```diff")
                lines.extend(line.rstrip("\n") for line in diff)
                lines.append("```")
            else:
                lines.append("*Files produce no textual diff (encoding difference only).*")
        else:
            lines.append("*Binary files differ.*")

        lines.append("")

    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wheel-diff",
        description=(
            "Diff two Python wheel files and write a markdown report listing "
            "files unique to each wheel, identical files, and per-file "
            "unified diffs of non-identical text files."
        ),
    )
    parser.add_argument(
        "wheel1",
        metavar="WHEEL_1",
        help="path to the first Python wheel (.whl)",
    )
    parser.add_argument(
        "wheel2",
        metavar="WHEEL_2",
        help="path to the second Python wheel (.whl)",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="write the report to FILE instead of stdout",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable verbose (debug) logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 on success, 1 on invalid wheel arguments."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        wheel1 = validate_wheel(args.wheel1)
        wheel2 = validate_wheel(args.wheel2)
    except WheelValidationError as exc:
        logger.error("invalid wheel: %s", exc)
        return 1

    logger.info("diffing %s vs %s", wheel1, wheel2)
    report = build_report(wheel1, wheel2)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(report, encoding="utf-8")
        logger.info("report written to %s", out_path)
        print(out_path)
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
