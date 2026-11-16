"""Verify distribution resources and exercise the installed wheel outside src/."""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest
from sample_data import COLORLOG_PYPI


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULE_NAMES = {"core.souffle", "metadata-normalisation.souffle", "src-normalisation.souffle"}


def _run(command, cwd):
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def distributions(tmp_path_factory):
    poetry = shutil.which("poetry")
    if poetry is None:
        pytest.skip("Poetry is required to build distribution artifacts")
    output = tmp_path_factory.mktemp("packaging")
    _run([poetry, "build", "--output", str(output)], cwd=PROJECT_ROOT)
    return next(output.glob("*.whl")), next(output.glob("*.tar.gz"))


def test_wheel_contains_rules(distributions):
    wheel, _ = distributions
    with zipfile.ZipFile(wheel) as archive:
        rules = {
            name.removeprefix("daleq4py/rules/")
            for name in archive.namelist()
            if name.startswith("daleq4py/rules/") and name.endswith(".souffle")
        }
        assert rules == RULE_NAMES
        for name in rules:
            assert archive.read(f"daleq4py/rules/{name}")


def test_sdist_contains_rules(distributions):
    _, sdist = distributions
    with tarfile.open(sdist) as archive:
        rules = {
            name.split("/src/daleq4py/rules/", 1)[1]
            for name in archive.getnames()
            if "/src/daleq4py/rules/" in name and name.endswith(".souffle")
        }
    assert rules == RULE_NAMES


@pytest.fixture(scope="module")
def installed_wheel(distributions, tmp_path_factory):
    if importlib.util.find_spec("pip") is None:
        pytest.skip("pip is required to install the built wheel")
    wheel, _ = distributions
    outside = tmp_path_factory.mktemp("installed-wheel")
    target = outside / "site-packages"
    _run([
        sys.executable, "-I", "-m", "pip", "--isolated", "install",
        "--disable-pip-version-check", "--no-cache-dir", "--no-index",
        "--no-deps", "--no-compile", "--target", str(target), str(wheel),
    ], cwd=outside)
    return outside, target


def _run_installed(installed_wheel, script, *args):
    outside, target = installed_wheel
    # -I ignores PYTHONPATH and the working directory. Explicitly select the
    # installed package ahead of any editable install used by the test runner.
    bootstrap = (
        "import sys; from pathlib import Path; "
        "target = Path(sys.argv.pop(1)); sys.path.insert(0, str(target)); "
        "import daleq4py; "
        "assert Path(daleq4py.__file__).parent == target / 'daleq4py';\n"
    )
    return _run([
        sys.executable, "-I", "-B", "-c", bootstrap + script,
        str(target), *map(str, args),
    ], cwd=outside)


def test_installed_wheel_loads_rules_without_repository(installed_wheel):
    _run_installed(installed_wheel, """
from daleq4py import inference
from daleq4py.project_idb import project_idb

edb = Path('session/edb')
edb.mkdir(parents=True)
(edb / 'content.tsv').write_text('F1\\tmod.py\\tpkg\\t@sha256\\tabc\\n')
(edb / 'package.tsv').write_text('F2\\tname\\tdemo-1.0\\n')

# Exercise rule loading and merging even on CI runners without Souffle.
inference.shutil.which = lambda _: None
try:
    inference.run_inference(edb)
except inference.InferenceError as exc:
    assert 'Soufflé is required' in str(exc), str(exc)
else:
    raise AssertionError('Expected the missing executable diagnostic')
merged = Path('session/mergedEDBAndRules.souffle').read_text()
for name in ('core.souffle', 'metadata-normalisation.souffle', 'src-normalisation.souffle'):
    assert '// from rules/' + name in merged
assert '<text-extensions-facts>' not in merged

idb = Path('session/idb')
(idb / 'content.tsv').write_text('F1\\tmod.py\\tpkg\\t@sha256\\tabc\\n')
(idb / 'package.tsv').write_text('F2\\tname\\tdemo-1.0\\n')
summary = project_idb(idb).read_text()
assert '| id | file | path | key | value |' in summary
assert '| id | key | value |' in summary
""")


@pytest.mark.skipif(shutil.which("souffle") is None, reason="souffle executable not on PATH")
def test_installed_wheel_compares_wheels(installed_wheel):
    outside, _ = installed_wheel
    wheel = outside / COLORLOG_PYPI.name
    shutil.copyfile(COLORLOG_PYPI, wheel)
    _run_installed(installed_wheel, """
from daleq4py.compare_wheels import main
wheel = sys.argv[1]
assert main([wheel, wheel, '--base-dir', str(Path('comparison').resolve())]) == 0
""", wheel)
