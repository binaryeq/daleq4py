# daleq4py

A command line tool to establish the equivalence of two alternatively built
Python wheels.

## Requirements

- Python >= 3.12
- [Poetry](https://python-poetry.org/) for dependency management and builds

## Building

Install dependencies (including the dev group) and build the project:

```sh
poetry install
poetry build
```

`poetry build` produces the wheel and source distribution under `dist/`.

## Running tests

```sh
poetry run pytest
```

## Running

### daleq4py

Compares two alternatively built wheels.

```sh
poetry run daleq4py WHEEL_A WHEEL_B
```

| Argument / option | Description |
| --- | --- |
| `WHEEL_A`, `WHEEL_B` | paths to the two wheels (`.whl`) to compare |
| `-v`, `--verbose` | enable verbose (debug) logging |
| `--version` | print the version and exit |

### extract-edb

Extracts a metadata EDB (extensional database) from a single wheel into
`<base-dir>/<wheel-name>/<session>/edb/`:

- `metadata-edb.tsv` — every file in the wheel's `*.dist-info` directory
  flattened into rows with columns `file`, `path`, `key`, `value`.
- `package-edb.tsv` — a two-row package descriptor with `name` (the
  `<package>-<version>` token, e.g. `colorlog-6.7.0`) and `distinfo` (the
  matching `*.dist-info` directory name).

The path of `metadata-edb.tsv` is printed on success; `package-edb.tsv` lives
in the same directory.

```sh
poetry run extract-edb WHEEL
```

| Argument / option | Description |
| --- | --- |
| `WHEEL` | path to the wheel (`.whl`) to extract metadata from |
| `--base-dir DIR` | root directory for the EDB tree; a relative path is resolved against the project root (default: `.souffle`) |
| `-v`, `--verbose` | enable verbose (debug) logging |

The test suite writes its EDB files to `.souffle-test/` instead.

Use `--help` with either command for the full list of options.
