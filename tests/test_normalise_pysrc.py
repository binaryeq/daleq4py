# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Tests for the Python source normaliser.

The normaliser round-trips source through ``ast.parse`` + ``ast.unparse``,
which removes comments, canonicalises layout, and forces ``\\n`` line endings.
"""

from __future__ import annotations

import ast
import textwrap

import pytest

from daleq4py.normalise_pysrc import main, normalise_source


# --- normalise_source: behaviour on a string ---


def _semantically_equal(src_a: str, src_b: str) -> bool:
    """True if two source strings produce the same AST (ignores comments/layout)."""
    return ast.dump(ast.parse(src_a)) == ast.dump(ast.parse(src_b))


def test_strips_full_line_comment():
    src = "# leading comment\nx = 1\n"
    out = normalise_source(src)
    assert "#" not in out
    assert "x = 1" in out


def test_strips_inline_comment():
    src = "x = 1  # trailing comment\n"
    out = normalise_source(src)
    assert "#" not in out
    assert "x = 1" in out


def test_preserves_module_docstring():
    src = '"""module doc."""\nx = 1\n'
    out = normalise_source(src)
    assert "module doc." in out


def test_preserves_function_docstring():
    src = textwrap.dedent(
        '''
        def f():
            """function doc."""
            return 1
        '''
    )
    out = normalise_source(src)
    assert "function doc." in out


def test_preserves_class_docstring():
    src = textwrap.dedent(
        '''
        class C:
            """class doc."""
            pass
        '''
    )
    out = normalise_source(src)
    assert "class doc." in out


def test_output_ends_with_single_newline():
    out = normalise_source("x = 1")
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_crlf_line_endings_are_normalised():
    src = "x = 1\r\ny = 2\r\n"
    out = normalise_source(src)
    assert "\r" not in out
    assert "x = 1" in out and "y = 2" in out


def test_semantics_are_preserved():
    src = textwrap.dedent(
        """
        # a comment
        def add(a, b):
            '''add two values.'''
            return a + b  # inline

        class P:
            x = 1
        """
    )
    out = normalise_source(src)
    assert _semantically_equal(src, out)


def test_normalisation_is_idempotent():
    src = "# c\nx = 1  # c\n"
    once = normalise_source(src)
    twice = normalise_source(once)
    assert once == twice


def test_syntax_error_raises():
    with pytest.raises(SyntaxError):
        normalise_source("def f(:\n    pass\n")


def test_empty_input_yields_just_newline():
    assert normalise_source("") == "\n"


# --- CLI: file / directory processing via main() ---


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_main_writes_normalised_file_under_output_dir(tmp_path):
    src = tmp_path / "in" / "mod.py"
    _write(src, "# comment\nx = 1\n")
    out_dir = tmp_path / "out"

    rc = main([str(src), "-o", str(out_dir)])

    assert rc == 0
    written = out_dir / "mod.py"
    assert written.exists()
    assert "#" not in written.read_text(encoding="utf-8")


def test_main_mirrors_directory_tree(tmp_path):
    root = tmp_path / "pkg"
    _write(root / "a.py", "# a\nx = 1\n")
    _write(root / "sub" / "b.py", "# b\ny = 2\n")
    _write(root / "sub" / "notes.txt", "ignored")
    out_dir = tmp_path / "out"

    rc = main([str(root), "-o", str(out_dir)])

    assert rc == 0
    # mirrored under <output>/<input-root-name>/...
    assert (out_dir / "pkg" / "a.py").exists()
    assert (out_dir / "pkg" / "sub" / "b.py").exists()
    # non-.py files are not copied
    assert not (out_dir / "pkg" / "sub" / "notes.txt").exists()


def test_main_in_place_overwrites_original(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("# c\nx = 1\n", encoding="utf-8")

    rc = main([str(src), "--in-place"])

    assert rc == 0
    assert "#" not in src.read_text(encoding="utf-8")


def test_main_writes_lf_line_endings_only(tmp_path):
    src = tmp_path / "in" / "mod.py"
    # write CRLF bytes directly to bypass universal-newline translation
    src.parent.mkdir(parents=True)
    src.write_bytes(b"# c\r\nx = 1\r\ny = 2\r\n")
    out_dir = tmp_path / "out"

    rc = main([str(src), "-o", str(out_dir)])

    assert rc == 0
    raw = (out_dir / "mod.py").read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")


def test_main_reports_failure_for_syntax_error(tmp_path, caplog):
    src = tmp_path / "in" / "broken.py"
    _write(src, "def f(:\n    pass\n")
    out_dir = tmp_path / "out"

    rc = main([str(src), "-o", str(out_dir)])

    assert rc == 1
    assert not (out_dir / "broken.py").exists()
    assert any("syntax error" in rec.message.lower() for rec in caplog.records)


def test_main_reports_failure_for_missing_path(tmp_path):
    rc = main([str(tmp_path / "does-not-exist"), "-o", str(tmp_path / "out")])
    assert rc == 1


def test_main_requires_output_or_in_place(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main([str(src)])


def test_main_output_and_in_place_are_mutually_exclusive(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main([str(src), "-i", "-o", str(tmp_path / "out")])
