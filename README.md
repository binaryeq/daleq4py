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

### normalise-pysrc

Normalises Python source files for binary-equivalence analysis by
round-tripping them through the stdlib AST (`ast.parse` + `ast.unparse`).
This:

- removes `#` comments (the AST does not preserve them);
- standardises layout to a canonical, deterministic form;
- writes `\n` line endings unconditionally.

Docstrings are kept (they are string-literal expressions, not comments).
Files that fail to parse are reported and skipped; the exit status is
non-zero if any file failed.

```sh
poetry run normalise-pysrc PATH [PATH ...] (-o DIR | -i)
```

| Argument / option | Description |
| --- | --- |
| `PATH` | one or more Python source files or directories (directories are recursed for `*.py`) |
| `-o`, `--output DIR` | write normalised files under `DIR`, mirroring the input tree |
| `-i`, `--in-place` | overwrite source files in place |
| `-v`, `--verbose` | enable verbose (debug) logging |

Exactly one of `--output` or `--in-place` is required.

### compare-wheels

Compares two wheels by partitioning their contents into three groups and
applying a different equality test to each:

1. **`*.dist-info` metadata** — runs `extract-edb`, `inference` and
   `project-idb` (twice, with and without `--remove-derivation`) on both
   wheels, then compares the reduced markdown summaries character by
   character.
2. **`*.py` source files** — normalises each shared `.py` member with the
   `normalise-pysrc` AST round-trip and compares the results character by
   character.
3. **All other files** — byte-by-byte comparison.

Members present in only one wheel count as a difference. The three per-group
booleans are combined with `and` to produce the overall result. Exit code:
`0` if the wheels are equal, `1` if they differ, `2` on error.

```sh
poetry run compare-wheels WHEEL_A WHEEL_B
```

| Argument / option | Description |
| --- | --- |
| `WHEEL_A`, `WHEEL_B` | paths to the two wheels (`.whl`) to compare |
| `--base-dir DIR` | root directory for EDB / IDB / projection artefacts; a relative path is resolved against the project root (default: `.souffle`) |
| `-v`, `--verbose` | enable verbose (debug) logging |

The programmatic entry point
`daleq4py.compare_wheels.compare_wheels(wheel_a, wheel_b)` returns a
`(bool, dict)` pair. The dict contains, for each of the two wheels:

- `wheels` — input wheel path
- `edb_dirs` — extracted EDB directory
- `idb_dirs` — inferred IDB directory
- `summaries`, `summaries_reduced` — full and reduced markdown projections
- `merged_rules` — path to `mergedEDBAndRules.souffle`

plus the per-group booleans `metadata_equal`, `py_files_equal`,
`other_files_equal`, and the lists of differing / one-sided member names for
the `.py` and other-file groups.

### run-experiments

Sweeps `sample-data/` and runs `compare-wheels` for every pair of builds of
the same `(package, version)`. The expected sample layout is
`sample-data/<package>/<version>/<build>/<wheel>.whl`. One markdown report
per pair is written to:

```
sample-data-results/<package>/<version>/<build_a>-vs-<build_b>.md
```

A top-level `sample-data-results/summary.md` is also written: it carries the
counts of equal / different / errored pairs and a details table (package,
build combination, overall / metadata / python source / other results) with
each row linking to its per-pair report.

Pipeline artefacts (EDB, IDB, projections, `mergedEDBAndRules.souffle`) for
each pair land under `sample-data-results/.artefacts/<package>/<version>/<build_a>-vs-<build_b>/`,
and the markdown reports link to them with relative paths. Each report lists:

- the overall result and the per-group results (metadata / `.py` / other);
- a table of artefact paths for both builds;
- the names of any members that differ or appear in only one build.

A pair that raises during comparison is recorded as `ERROR` in its report;
the sweep continues with the next pair. Exit code: `0` if no pair errored,
`1` otherwise.

```sh
poetry run run-experiments
```

| Argument / option | Description |
| --- | --- |
| `--sample-dir DIR` | sample-data root (default: `sample-data`) |
| `--results-dir DIR` | output root (default: `sample-data-results`) |
| `-v`, `--verbose` | enable verbose (debug) logging |

Use `--help` with any command for the full list of options.
