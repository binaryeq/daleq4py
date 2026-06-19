# Author: Jens Dietrich (https://github.com/jensdietrich/), co-authored by claude code

"""Concrete paths to the sample wheels under ``tests/data``.

Each package is shipped as three alternatively built wheels — ``pypi``,
``macaron`` and ``ossr`` — that are meant to be compared against each other.
Tests reference these constants directly so it is obvious which wheel is used.
"""

from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# colorlog 6.7.0 has license at colorlog-6.7.0.dist-info/LICENSE
COLORLOG_PYPI = DATA_DIR / "colorlog/6.7.0/pypi/colorlog-6.7.0-py2.py3-none-any.whl"
COLORLOG_MACARON = DATA_DIR / "colorlog/6.7.0/macaron/colorlog-6.7.0-py2.py3-none-any.whl"
COLORLOG_OSSR = DATA_DIR / "colorlog/6.7.0/ossr/colorlog-6.7.0-py2.py3-none-any.whl"
# A fresh build of colorlog 6.7.0 has license at colorlog-6.7.0.dist-info/licenses/LICENSE and
# is built with Metadata-Version 2.4 instead of 2.1
COLORLOG_FRESH_PYTHON_M_BUILD = DATA_DIR / "colorlog/6.7.0/fresh_python_-m_build/colorlog-6.7.0-py2.py3-none-any.whl"

# colorlog 6.10.1 has license at colorlog-6.10.1.dist-info/licenses/LICENSE
COLORLOG_6_10_1_PYPI = DATA_DIR / "colorlog/6.10.1/pypi/colorlog-6.10.1-py3-none-any.whl"

# arrow 1.2.1
ARROW_PYPI = DATA_DIR / "arrow/1.2.1/pypi/arrow-1.2.1-py3-none-any.whl"
ARROW_MACARON = DATA_DIR / "arrow/1.2.1/macaron/arrow-1.2.1-py3-none-any.whl"
ARROW_OSSR = DATA_DIR / "arrow/1.2.1/ossr/arrow-1.2.1-py3-none-any.whl"

# autopep8 2.1.2
AUTOPEP8_PYPI = DATA_DIR / "autopep8/2.1.2/pypi/autopep8-2.1.2-py2.py3-none-any.whl"
AUTOPEP8_MACARON = DATA_DIR / "autopep8/2.1.2/macaron/autopep8-2.1.2-py2.py3-none-any.whl"
AUTOPEP8_OSSR = DATA_DIR / "autopep8/2.1.2/ossr/autopep8-2.1.2-py2.py3-none-any.whl"

# Every sample wheel, for tests that should hold for all of them.
ALL_WHEELS = (
    COLORLOG_PYPI,
    COLORLOG_MACARON,
    COLORLOG_OSSR,
    COLORLOG_FRESH_PYTHON_M_BUILD,
    COLORLOG_6_10_1_PYPI,
    ARROW_PYPI,
    ARROW_MACARON,
    ARROW_OSSR,
    AUTOPEP8_PYPI,
    AUTOPEP8_MACARON,
    AUTOPEP8_OSSR,
)
