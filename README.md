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

Once installed, invoke the CLI with two wheels to compare:

```sh
poetry run daleq4py WHEEL_A WHEEL_B
```

Use `poetry run daleq4py --help` for the full list of options.
