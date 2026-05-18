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

- `metadata.tsv` — every file in the wheel's `*.dist-info` directory
  flattened into rows with columns `file`, `path`, `key`, `value`.
- `package.tsv` — a two-row package descriptor with `name` (the
  `<package>-<version>` token, e.g. `colorlog-6.7.0`) and `distinfo` (the
  matching `*.dist-info` directory name).

The path of `metadata.tsv` is printed on success; `package.tsv` lives in the
same directory.

### inference

Runs Soufflé on the EDB produced by `extract-edb`. The script copies
`rules/core.souffle` to `<session>/mergedEDBAndRules.souffle`, substitutes the
four `<*-facts>` placeholders with absolute paths to the EDB (input) and IDB
(output) TSVs, creates the sibling `<session>/idb/` directory, then invokes
`souffle` to produce `idb/metadata.tsv` and `idb/package.tsv`.

```sh
poetry run inference EDB_DIR
```

| Argument / option | Description |
| --- | --- |
| `EDB_DIR` | path to the `edb/` directory produced by `extract-edb` |
| `-v`, `--verbose` | enable verbose (debug) logging |

The `souffle` binary must be on `PATH`.

### project-idb

Renders a human-readable markdown summary of an IDB directory. For every
`*.tsv` file in the input folder it emits a section whose header is the
predicate name (the filename stem) and whose body is a markdown table; the
column headers are inferred from the matching `.decl` declaration in any
`rules/*.souffle` file. The summary is written to
`<session>/normalisation-summary.md`.

```sh
poetry run project-idb IDB_DIR
```

| Argument / option | Description |
| --- | --- |
| `IDB_DIR` | path to the `idb/` directory produced by `inference` |
| `--remove-derivation` | drop the leading `id` column from each table and write to `normalisation-summary-reduced.md` instead of `normalisation-summary.md` |
| `-v`, `--verbose` | enable verbose (debug) logging |

### parse-provenance

Parses a derived-fact provenance id (an encoded proof tree such as
`R1[F1,R2[F2,F3]]`) and prints the resulting derivation tree. The grammar
lives in `src/daleq4py/proof.lark` and is the Lark equivalent of the
antlr4 `Proof.g4` grammar in the daleq Java project.

```sh
poetry run parse-provenance 'R1[F1,R2[F2,F3,F4]]'
```

Output:

```
R1
├── F1
└── R2
    ├── F2
    ├── F3
    └── F4
```

| Argument / option | Description |
| --- | --- |
| `EXPRESSION` | the derivation id to parse |
| `-v`, `--verbose` | enable verbose (debug) logging |

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
