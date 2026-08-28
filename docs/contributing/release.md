# Release
> Applies to kgmd 0.2.x

For maintainers cutting a kgmd release. This page states where the version number lives, the exact
sequence that publishes to PyPI, what is prohibited, and the manual verification that the automated
suite structurally cannot perform.

## Versioning

`__version__` in `kgmd/__init__.py` is the single source of truth:

```text
kgmd/__init__.py    __version__ = "0.2.0"
```

`pyproject.toml` declares `dynamic = ["version"]` and points hatchling at that file:

```text
[tool.hatch.version]
path = "kgmd/__init__.py"
```

So the built wheel and sdist take their version from the module attribute. There is no second copy to
keep in sync, and `pyproject.toml` carries no literal version string. `tests/test_docs.py` reads the
same attribute to check documentation stamps, which is why a bump propagates into the documentation
gate immediately.

## Steps

1. **Bump the version.** Edit `__version__` in `kgmd/__init__.py` and nowhere else.

2. **Update the version stamp on every page under `docs/`.** Line 2 of each page is
   `> Applies to kgmd X.Y.x`, and `tests/test_docs.py` compares its major and minor against
   `kgmd.__version__`. There are 16 pages today, and the check is discovery-based — it globs
   `docs/**/*.md`, so a page added since the last release is included automatically.

   A bump across a minor boundary therefore turns the suite red until every stamp matches. That is
   deliberate: it forces a maintainer to walk the whole documentation set at each release rather than
   shipping pages that silently describe an older version. A patch bump within the same minor
   (`0.2.0` to `0.2.1`) leaves the stamps valid, because the stamp names the minor series.

3. **Run the full local check sequence** from [the development page](./development.md):

   ```bash
   make format
   make lint
   make test
   ```

   All three must be clean before the release is tagged. CI will run `ruff check .` and `pytest -v`
   across Python 3.10 to 3.13, but a failure discovered after publication is not recoverable — PyPI
   does not allow re-uploading a version.

4. **Work through the pre-release verification checklist** below. It is not automated and it is not
   optional.

5. **Publish a GitHub Release.** Creating and publishing the release is the trigger:
   `.github/workflows/publish.yml` runs `on: release: types: [published]`. The job runs on
   `ubuntu-latest` in the `pypi` environment with `permissions: id-token: write`, checks out the
   repository, sets up Python 3.12, installs `build`, runs `python -m build`, and uploads with
   `pypa/gh-action-pypi-publish@release/v1`.

   Authentication is OIDC trusted publishing. The `id-token: write` permission lets the workflow
   mint a short-lived identity token that PyPI verifies against the configured trusted publisher; no
   long-lived credential exists anywhere in the repository or in the environment. The `pypi`
   environment exists so that its protection rules gate who can start a publish.

6. **Verify the published artifact** by installing it from PyPI in a clean virtualenv, per the
   checklist item below.

## Prohibited

- **Manual `twine upload`.** Publication happens only through the release workflow. A hand-uploaded
  artifact has no provenance, was not built from a tagged checkout, and bypasses the `pypi`
  environment's protection rules.
- **Committed API tokens.** Trusted publishing removes the need for a PyPI token entirely. A token
  in the repository, in a workflow file, or in a plain repository variable is a defect regardless of
  scope.
- **`--no-verify`.** Never bypass a commit hook or a check to get a release out.
- **Editing the version anywhere except `kgmd/__init__.py`.** Adding a literal `version = ` to
  `pyproject.toml` conflicts with the dynamic declaration; patching a built artifact desynchronises
  it from the module attribute that `tests/test_docs.py` reads.
- **Reusing a version number.** PyPI rejects a re-upload. A mistake in a published release is fixed
  by a new version, not by a replacement.

## Pre-release verification checklist

The automated suite deliberately makes no provider calls and requires no credential, so it cannot
execute any example that builds a real graph, cannot connect a real MCP client, and cannot resolve a
Windows path from a Linux runner. That residue is verified by hand, once per release. Tick every box:

- [ ] Every `bash` block in [the quickstart](../quickstart.md) executed verbatim, in order, against a
      fresh corpus — not a corpus left over from a previous run. Each step's actual output matches
      what the page says to expect.
- [ ] All three walkthroughs in `docs/examples/` — [personal notes](../examples/personal-notes.md),
      [MCP assistant](../examples/mcp-assistant.md), and [graph export](../examples/graph-export.md)
      — executed end to end against the `tests/fixtures/` corpus from a git checkout. Any pinned
      entity or relation count on the fixture path still matches.
- [ ] `kgmd mcp` connected from a real assistant client using the configuration block in
      [the MCP guide](../guides/mcp.md), with at least one tool call round-tripped and its result
      inspected. Confirm the registered tool names in the guide match what the client lists.
- [ ] The Windows global configuration path `%LOCALAPPDATA%\kgmd\kgmd\config.yaml` confirmed on an
      actual Windows machine. This path is derived from the `platformdirs` source and has never been
      executed on Windows; the doubled `kgmd` segment is expected but unverified. Until a maintainer
      runs it on Windows, [the configuration reference](../reference/configuration.md) must keep
      saying so.
- [ ] `pip install kgmd` verified in a clean virtualenv on at least one supported interpreter,
      including the loadable-SQLite-extension caveat: confirm both that a capable interpreter works
      and that an interpreter without extension support produces the symptom documented on
      [the installation page](../install.md).
- [ ] Version stamps updated across `docs/` and `make test` clean, confirming step 2 landed.
- [ ] The three inert configuration keys still have no read site in `kgmd/`, or, if one gained an
      implementation, [the configuration reference](../reference/configuration.md) no longer marks it
      as having no effect.

### Timings to re-verify

Two documented targets are measured, not asserted, and drift as the tool and the pages change. Re-time
both each release, from a clean state, and correct the pages if a target is missed:

- [ ] **Onboarding: under 15 minutes** of active work from nothing installed to a queryable graph,
      using only [the installation page](../install.md) and [the quickstart](../quickstart.md), on a
      clean machine. Provider latency during `kgmd build` counts as waiting, not active work.
- [ ] **Contributor setup: under 10 minutes** from a fresh clone to a clean `make lint` and
      `make test`, using only [the development page](./development.md).

Record the measured numbers in the release notes so the next maintainer has a baseline to compare
against rather than re-deriving one.

**No baseline exists yet.** Neither target has been timed: both require a human reader on a clean
machine, and the onboarding walk additionally requires a provider credential. The first maintainer to
run this checklist establishes the baseline.
