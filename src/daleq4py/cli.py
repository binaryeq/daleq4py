"""Command line interface for daleq4py.

Uses argparse. The CLI layer stays thin: it validates the two wheel arguments
and delegates the actual comparison to the modules under ``daleq4py``.
"""

from __future__ import annotations

import argparse
import logging
import sys

from daleq4py import __version__
from daleq4py.wheel import WheelValidationError, validate_wheel

logger = logging.getLogger("daleq4py")


def _wheel_arg(raw_path: str) -> "object":
    """argparse ``type`` callback: validate a wheel path argument."""
    try:
        return validate_wheel(raw_path)
    except WheelValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daleq4py",
        description=(
            "Establish the equivalence of two alternatively built Python wheels."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable verbose (debug) logging",
    )
    parser.add_argument(
        "wheel_a",
        type=_wheel_arg,
        metavar="WHEEL_A",
        help="path to the first Python wheel (.whl) to compare",
    )
    parser.add_argument(
        "wheel_b",
        type=_wheel_arg,
        metavar="WHEEL_B",
        help="path to the second Python wheel (.whl) to compare",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    logger.info("comparing wheels:")
    logger.info("  WHEEL_A: %s", args.wheel_a)
    logger.info("  WHEEL_B: %s", args.wheel_b)

    # TODO: delegate to the comparison modules once their behaviour is defined.
    logger.warning("comparison not implemented yet — input validation only")

    return 0


if __name__ == "__main__":
    sys.exit(main())
