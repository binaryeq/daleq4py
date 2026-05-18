# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Tests for the provenance parser.

Adapted from the Java tests at
https://github.com/binaryeq/daleq/blob/main/src/test/java/io/github/bineq/daleq/souffle/provenance/ProvenanceParserTests.java
"""

import pytest
from lark.exceptions import LarkError

from daleq4py.parse_provenance import DerivationNode, format_tree, parse


def _print(input_str: str, root: DerivationNode) -> None:
    """Mirror the Java helper that prints the derivation for inspection."""
    print("***************************")
    print(f'derivation tree for "{input_str}":')
    print(format_tree(root))
    print("***************************")


def test_single_id_has_no_children():
    text = "R1"
    root = parse(text)
    _print(text, root)

    assert root.id == "R1"
    assert root.children == []


def test_flat_children():
    text = "R1[F1,F2]"
    root = parse(text)
    _print(text, root)

    assert root.id == "R1"
    assert len(root.children) == 2
    assert root.children[0].id == "F1"
    assert root.children[1].id == "F2"


def test_nested_children():
    text = "R1[F1,R2[F2,F3,F4]]"
    root = parse(text)
    _print(text, root)

    assert root.id == "R1"
    assert len(root.children) == 2
    assert root.children[0].id == "F1"

    complex_child = root.children[1]
    assert complex_child.id == "R2"
    assert len(complex_child.children) == 3
    assert complex_child.children[0].id == "F2"
    assert complex_child.children[1].id == "F3"
    assert complex_child.children[2].id == "F4"


def test_ids_with_underscores_and_mixed_case():
    text = "_R1_xX[_F1_xX,_F2_xX]"
    root = parse(text)
    _print(text, root)

    assert root.id == "_R1_xX"
    assert len(root.children) == 2
    assert root.children[0].id == "_F1_xX"
    assert root.children[1].id == "_F2_xX"


def test_whitespace_is_tolerated():
    text = "R1 [ F1 ,  F2 ]"
    # the Java test feeds the parser a trailing-space variant
    root = parse("R1 [ F1 ,  F2 ] ")
    _print(text, root)

    assert root.id == "R1"
    assert len(root.children) == 2
    assert root.children[0].id == "F1"
    assert root.children[1].id == "F2"


# --- additional cases the Java tests don't cover ---


def test_invalid_input_raises():
    with pytest.raises(LarkError):
        parse("R1[")


def test_empty_input_raises():
    with pytest.raises(LarkError):
        parse("")


def test_format_tree_renders_nested_structure():
    rendered = format_tree(parse("R1[F1,R2[F2,F3]]"))
    # the root is on the first line; F1 and R2 are children; F2/F3 nest below R2.
    lines = rendered.splitlines()
    assert lines[0] == "R1"
    assert "F1" in rendered
    assert "R2" in rendered
    assert "F2" in rendered
    assert "F3" in rendered
