# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Parse derived-fact provenance ids into a derivation tree.

A derived id encodes the proof tree used to produce a fact: each node is the
id of a fact or rule, optionally followed by a bracketed list of child nodes.
This module mirrors the ``ProvenanceParser`` from the daleq Java project --
its grammar lives next to this file in :file:`proof.lark`.

The public surface is small:

    >>> from daleq4py.parse_provenance import parse
    >>> root = parse("R1[F1,R2[F2,F3]]")
    >>> root.id
    'R1'
    >>> [c.id for c in root.children]
    ['F1', 'R2']
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lark import Lark, Transformer

logger = logging.getLogger("daleq4py")

GRAMMAR_FILE = Path(__file__).with_name("proof.lark")


@dataclass(frozen=True)
class DerivationNode:
    """One node in a derivation tree: a fact or rule id and its children."""

    id: str
    children: list["DerivationNode"] = field(default_factory=list)


class _ToAST(Transformer):
    """Transform the Lark parse tree into :class:`DerivationNode` objects."""

    def node(self, items):
        # ``items`` is ``[ID_token]`` or ``[ID_token, children_list]``.
        node_id = str(items[0])
        children = items[1] if len(items) > 1 else []
        return DerivationNode(node_id, children)

    def children(self, items):
        return list(items)


# A single Lark parser is built at import time and reused on every call.
_PARSER = Lark(
    GRAMMAR_FILE.read_text(encoding="utf-8"),
    parser="lalr",
    transformer=_ToAST(),
)


def parse(text: str) -> DerivationNode:
    """Parse ``text`` and return the root :class:`DerivationNode`."""
    return _PARSER.parse(text)


def format_tree(node: DerivationNode) -> str:
    """Render a :class:`DerivationNode` as an indented ASCII tree."""
    lines: list[str] = [node.id]
    _render_children(node, "", lines)
    return "\n".join(lines)


def _render_children(node: DerivationNode, prefix: str, lines: list[str]) -> None:
    last = len(node.children) - 1
    for i, child in enumerate(node.children):
        is_last = i == last
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{child.id}")
        child_prefix = prefix + ("    " if is_last else "│   ")
        _render_children(child, child_prefix, lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parse-provenance",
        description=(
            "Parse a derived-fact provenance id and print its derivation tree."
        ),
    )
    parser.add_argument(
        "expression",
        metavar="EXPRESSION",
        help="the derivation id to parse, e.g. 'R1[F1,R2[F2,F3]]'",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable verbose (debug) logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Prints the parsed derivation tree and returns an exit code."""
    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        root = parse(args.expression)
    except Exception as exc:  # lark.exceptions.LarkError or subclasses
        logger.error("could not parse %r: %s", args.expression, exc)
        return 1

    print(format_tree(root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
