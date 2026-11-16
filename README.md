# daleq4py

A command line tool to establish the equivalence of two alternatively built Python wheels.
Similar to and inspired by the [daleq](https://github.com/binaryeq/daleq) tool for Java.
The approach is described and evaluated in more details in [this paper](https://arxiv.org/abs/2607.21888).

> **External dependency:** Installing `daleq4py` from PyPI installs only the
> Python package. The separately installed [Soufflé](https://souffle-lang.github.io/)
> executable is required for inference-based commands; it is not bundled in
> the `py3-none-any` wheel.

## Requirements

- Python >= 3.14
- [Poetry](https://python-poetry.org/) for dependency management and builds
- [Soufflé](https://souffle-lang.github.io/) available on `PATH` for
  inference-based commands: `inference`, `compare-wheels`, and
  `run-experiments`. Soufflé is a separately installed system executable, not
  a Python package dependency.

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

## Continuous integration

Every pull request runs the [test workflow](.github/workflows/test.yaml) on GitHub Actions. It creates a clean Python environment from `poetry.lock`, installs the package and its development dependencies, then runs the complete pytest suite. Tests that require the separately installed Soufflé executable skip when it is not available on the runner.

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

Extracts a content EDB (extensional database) from a single wheel into
`<base-dir>/<wheel-name>/<session>/edb/`:

- `content.tsv` — **every** member of the wheel flattened into rows with
  columns `file`, `path`, `key`, `value`. Each member contributes:
  - **Explicit keys** when the member is a recognised metadata file inside
    `*.dist-info/`: RFC 822 `Key: value` pairs for `METADATA` / `WHEEL`,
    and one `(packaged-file-path, sha256=…,size)` row per line of `RECORD`.
  - **Synthetic keys** (every member): `@sha256`, `@norm/sha256` (text files
    only — `.py` via AST round-trip, other text via LF normalisation), and
    — when `--src` is supplied — `@src-exists`, `@src-exists-moved`,
    `@src/sha256`, `@src/norm/sha256`.
- `package.tsv` — a two-row package descriptor with `name` (the
  `<package>-<version>` token, e.g. `colorlog-6.7.0`) and `distinfo` (the
  matching `*.dist-info` directory name).

The path of `content.tsv` is printed on success; `package.tsv` lives in the
same directory.

### inference

Runs Soufflé on the EDB produced by `extract-edb`. The script concatenates
every `rules/*.souffle` file (each block prefixed with a `// from <path>`
provenance comment) into `<session>/mergedEDBAndRules.souffle`, substitutes
the four `<*-facts>` placeholders with absolute paths to the EDB (input) and
IDB (output) TSVs, creates the sibling `<session>/idb/` directory, then
invokes `souffle` to produce `idb/content.tsv` and `idb/package.tsv`.

```sh
poetry run inference EDB_DIR
```

| Argument / option | Description |
| --- | --- |
| `EDB_DIR` | path to the `edb/` directory produced by `extract-edb` |
| `-v`, `--verbose` | enable verbose (debug) logging |

Soufflé must be installed separately and its `souffle` binary must be on
`PATH`.

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
poetry run extract-edb WHEEL [--src ZIP]
```

| Argument / option | Description |
| --- | --- |
| `WHEEL` | path to the wheel (`.whl`) to extract content from |
| `--src ZIP` | optional "trusted" wheel/zip whose members define the baseline for the `@src-*` synthetic keys; when omitted, those keys are not emitted |
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
Python source is parsed from its original bytes, respecting PEP 263 encoding
declarations and UTF-8 byte order marks. Normalised output is written as UTF-8.
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

Invalid Python source or source encoding causes extraction and comparison to
fail with an error; it is never replaced with lossy text for normalised hashes.

```sh
poetry run compare-wheels WHEEL_A WHEEL_B [--src ZIP]
```

| Argument / option | Description |
| --- | --- |
| `WHEEL_A`, `WHEEL_B` | paths to the two wheels (`.whl`) to compare |
| `--src ZIP` | optional "trusted" wheel/zip whose `.py` members define the baseline set legitimately expected in a built wheel; any `.py` member of `WHEEL_A` or `WHEEL_B` not present in this baseline is flagged as suspicious. May be the same path as `WHEEL_A`, `WHEEL_B`, or any other zip. Does **not** affect the equality booleans — it's informational |
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
the `.py` and other-file groups. When `src` is supplied, the dict also
carries `src` (the baseline path) and the two suspicious-member lists
`py_files_unexpected_in_a` / `py_files_unexpected_in_b`.

### wheel-diff

Produces a markdown diff report between two wheels. The report lists, with
SHA-256 digests, the files present in only one wheel, the files that are
byte-identical in both, and the files that are present in both but differ —
each with a unified textual diff (for files that decode as text) or a
`*Binary files differ.*` note.

```sh
poetry run wheel-diff WHEEL_1 WHEEL_2 [-o FILE]
```

| Argument / option | Description |
| --- | --- |
| `WHEEL_1`, `WHEEL_2` | paths to the two wheels (`.whl`) to diff |
| `-o`, `--output FILE` | write the report to `FILE` instead of stdout |
| `-v`, `--verbose` | enable verbose (debug) logging |

Adapted from `pyeqpkg/diff-script/wheel-diff.py`.

### run-experiments

Sweeps `sample-data/` and runs `compare-wheels` for every pair of builds of
the same `(package, version)`. The expected sample layout is
`sample-data/<package>/<version>/<build>/<wheel>.whl`. One markdown report
per pair is written to:

```
sample-data-results/<package>/<version>/<build_a>-vs-<build_b>.md                    # comparison report
sample-data-results/<package>/<version>/<build_a>-vs-<build_b>-diff.md               # wheel-diff report
sample-data-results/<package>/<version>/<build_a>-vs-<build_b>-idb-diff.md           # unified diff of full IDB projections
sample-data-results/<package>/<version>/<build_a>-vs-<build_b>-idb-reduced-diff.md   # unified diff of reduced IDB projections
```

The comparison report links to all three diff reports in its header. The two
IDB-diff reports are only produced when the comparison pipeline ran
successfully (they read the projection files it writes).

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

For each pair the sweep also picks a "trusted" baseline (`src`) per the
following policy and passes it to `compare-wheels`: if `macaron` is one of
the pair's builds, the macaron wheel is `src`; otherwise the `ossr` wheel is
`src`. Each per-pair report ends with a **Trust check** section listing any
`.py` members in either build that are absent from the baseline. The trust
check is informational and does not affect the per-group / overall booleans.

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
