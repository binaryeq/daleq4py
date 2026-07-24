# Release checklist

Publishing to PyPI is triggered by pushing a tag matching `v*.*.*`; see
`.github/workflows/pypi-publish.yml`.

## One-time setup (already required before the first release)

1. **GitHub Environment**: in `binaryeq/daleq4py` → Settings → Environments →
   create an environment named `pypi` (matches `environment: pypi` in the
   workflow). Optionally add required reviewers for extra protection on
   publishes.
2. **PyPI Trusted Publisher (pending publisher)**: since `daleq4py` doesn't
   exist on PyPI yet, register it *before* the first release at
   https://pypi.org/manage/account/publishing/ with:
   - PyPI Project Name: `daleq4py`
   - Owner: `binaryeq`
   - Repository name: `daleq4py`
   - Workflow name: `pypi-publish.yml`
   - Environment name: `pypi`

   Once the first successful publish happens, PyPI converts this into a
   normal (non-pending) trusted publisher tied to the now-existing project,
   manageable from the project's own "Publishing" settings page.

## Release steps

1. Bump the version in **both**:
   - `pyproject.toml` (`[project].version`)
   - `src/daleq4py/__init__.py` (`__version__`)

   to the same value, e.g. `0.1.0`.
2. Commit and push to `main`.
3. Tag and push the tag:
   ```sh
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. The workflow runs tests, builds, and publishes to PyPI automatically.
   Watch the Actions tab; the `publish` job will pause for approval if the
   `pypi` environment has required reviewers configured.

## Local verification before tagging

Run these locally to catch problems before pushing a tag:

- `poetry check` — validates `pyproject.toml` metadata (license expression
  etc.).
- `poetry build` — confirms the sdist/wheel build succeeds and includes
  `LICENSE.md`. Check with:
  ```sh
  unzip -l dist/*.whl | grep dist-info
  ```
  You should see `daleq4py-<version>.dist-info/licenses/LICENSE.md`.
- `poetry run pytest` — confirms tests pass.

Note: end-to-end verification of the publish step itself only happens on the
first real tag push — there's no local way to dry-run the trusted-publishing
OIDC exchange.
