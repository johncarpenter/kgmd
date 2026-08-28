# Development
> Applies to kgmd 0.1.x

For contributors changing kgmd's code or its documentation. Working through this page from a fresh
clone gets you an installed development environment, a clean local check run that mirrors the
automated gate, and the conventions that decide whether a change is finished.

## Set up

```bash
git clone https://github.com/johncarpenter/kgmd.git
cd kgmd
python -m venv .venv && source .venv/bin/activate
make install
```

`make install` runs `pip install -e ".[dev]"`, which installs kgmd in editable mode plus the dev
extras declared in `pyproject.toml`: `pytest>=7.0`, `pytest-mock>=3.10`, and `ruff>=0.4`.

Supported interpreters are Python 3.10, 3.11, 3.12, and 3.13 (`requires-python = ">=3.10"`).

Your interpreter must be built with loadable SQLite extension support. `kgmd/db.py` calls
`conn.enable_load_extension(True)` and then `sqlite_vec.load(conn)` on every connection, so an
interpreter compiled without that capability cannot open a corpus database at all — the failure
appears the first time any command touches `.kgmd/graph.db`, not at install time. The symptom and
the remedy are on [the installation page](../install.md).

No provider credential is needed to develop or to run the test suite. The suite mocks the LLM and
never computes an embedding.

## The local check sequence

Run these three in order before pushing. Each target is one line in the `Makefile`; the exact
commands are:

| Target | Command it runs |
|---|---|
| `make format` | `ruff format kgmd/ tests/` then `ruff check --fix kgmd/ tests/` |
| `make lint` | `ruff check kgmd/ tests/` |
| `make test` | `python -m pytest tests/ -v` |

Two more targets exist for release mechanics rather than day-to-day work:

| Target | Command it runs |
|---|---|
| `make build` | `python -m build` |
| `make clean` | `rm -rf dist/ build/ *.egg-info` plus removal of every `__pycache__` directory |

Ruff is configured in `pyproject.toml`: `line-length = 100`, `target-version = "py310"`, and lint
rule sets `E`, `F`, `I`, `W`. `I` means import sorting is enforced, so a hand-ordered import block
that ruff disagrees with fails `make lint`. Pytest is configured with `testpaths = ["tests"]`, which
is why a bare `pytest` from the repository root collects the same files as `make test`.

## What CI enforces

`.github/workflows/ci.yml` runs on every push to `main` and every pull request targeting `main`. It
installs `pip install -e ".[dev]"` on `ubuntu-latest` across a four-way matrix — Python 3.10, 3.11,
3.12, and 3.13 — and then runs exactly two steps:

```bash
ruff check .
pytest -v
```

Two differences from the local sequence matter:

- CI lints `.` (the whole repository), while `make lint` lints only `kgmd/` and `tests/`. A lint
  error in a root-level or tooling Python file passes locally and fails in CI.
- CI runs `ruff check` but never `ruff format --check`. Formatting drift is therefore not caught by
  the gate at all — it is caught only by you running `make format` locally. Run it; otherwise
  reformatting noise accumulates in unrelated diffs.

There is no separate documentation job. The documentation checks are ordinary tests in
`tests/test_docs.py` and run inside `pytest -v` on all four interpreters.

## Test conventions

Tests are plain pytest functions — `def test_something():` at module level. There are no test
classes anywhere in `tests/`, and new tests should not introduce one.

`tests/conftest.py` provides a four-stage fixture chain; take the cheapest fixture that gives you
what you need:

| Fixture | Builds on | What you get |
|---|---|---|
| `tmp_corpus` | `tmp_path` | A `corpus/` directory with every `tests/fixtures/*.md` note copied in. |
| `initialized_corpus` | `tmp_corpus` | Adds `.kgmd/` with `logs/`, `prompts/`, a default `config.yaml`, and a `graph.db` created by `init_db`. |
| `db_conn` | `initialized_corpus` | An open connection to that empty database, closed on teardown. |
| `seeded_db` | `initialized_corpus` | An open connection to a database populated with one document, two chunks, one extraction run, five entities, four mentions, and four relations. |

Rules the existing suite follows:

- **The LLM is mocked at the `litellm.completion` seam.** Tests patch it where it is looked up, for
  example `patch("kgmd.llm.litellm.completion", return_value=mock_response)` for extraction and
  resolution, and `patch("kgmd.induce.litellm.completion", ...)` for schema induction. Never mock
  kgmd's own functions to stand in for the provider.
- **Embeddings are never computed.** No test loads a fastembed model. Vectors are hand-packed
  float32 blobs — `struct.pack(f"{dim}f", *vec)` — and inserted directly, which is the same wire
  format `kgmd/embed.py` writes. Similarity behaviour is tested by choosing the vectors, not by
  embedding text.
- **No network.** Nothing in the suite opens a socket, and no test requires a provider credential.
- **No sleeps.** There are no timing-dependent waits; if a test needs a state transition, it drives
  the transition directly.
- **No absolute paths.** Every filesystem test roots itself in `tmp_path` via the fixture chain.

Test modules are named after the unit under test: `test_chunk.py`, `test_db.py`, `test_export.py`,
`test_extract.py`, `test_induce.py`, `test_mcp.py`, `test_query.py`, `test_resolve.py`, and
`test_docs.py`.

## Documentation is part of the change

`tests/test_docs.py` enforces coverage in both directions by introspecting the real surface — Click
command objects for the CLI, `DEFAULT_CONFIG` for configuration, an AST scan of `kgmd/mcp_server.py`
for tool names, and the `export` format choices — and comparing it against the headings, table rows,
and code spans in `docs/`.

The consequence is symmetrical:

- Adding a command, a parameter, a configuration key, an MCP tool, or an export format **without
  documenting it** fails the suite.
- Documenting a command, parameter, key, tool, or format **that does not exist** also fails the
  suite. A stale flag left in a table after the code dropped it is a build failure, as is a
  `` `kgmd ...` `` invocation naming a subcommand that was never added.

So a capability change and its documentation ship in the same commit. There is no follow-up window
in which the docs are allowed to be wrong.

The version stamp on line 2 of every page (`> Applies to kgmd 0.1.x`) is checked against
`kgmd/__init__.py`. Bumping `__version__` across a minor boundary turns every page red until the
stamps are updated — see [the release process](./release.md).

The suite also rejects, on every page: the usual unwritten-placeholder markers and the "soon"
phrasing (the test greps for them literally, so they cannot be spelled out on a page — read
`test_no_unwritten_placeholders` in `tests/test_docs.py` for the exact list), developer absolute
paths, credential-shaped strings, internal links that do not resolve on disk, and any page more than
two links from [the documentation index](../README.md). Pages must keep the fixed prologue — H1,
stamp, blank line, audience paragraph — and exactly one H1.

## Where to put things

| Change | Code goes in | Documentation that must be updated |
|---|---|---|
| New pipeline stage | A new `kgmd/<stage>.py` exposing a `run_<stage>(conn, ...)` function, wired into `kgmd/cli.py` as a subcommand and into the `build` orchestration | [`../reference/cli.md`](../reference/cli.md) command entry; [`../concepts.md`](../concepts.md) if it introduces vocabulary |
| New read capability | `kgmd/query.py`, then surfaced from `kgmd/cli.py` and, if it should be agent-visible, `kgmd/mcp_server.py` | [`../reference/cli.md`](../reference/cli.md), plus [`../guides/mcp.md`](../guides/mcp.md) when a tool is registered |
| New prompt | A text asset in `kgmd/prompts/`, loaded through the same override lookup the other stages use | [`./architecture.md`](./architecture.md) prompt asset list |
| New configuration key | `DEFAULT_CONFIG` in `kgmd/config.py`, **and** the stage that reads it — a key with no read site is inert and must be documented as such | [`../reference/configuration.md`](../reference/configuration.md) |
| New export format | `kgmd/export.py` plus the format choice in the `export` command in `kgmd/cli.py` | [`../reference/export.md`](../reference/export.md) |
| New table or column | `SCHEMA_SQL` in `kgmd/schema.py` only; nothing else issues DDL | [`./architecture.md`](./architecture.md) if it changes the module contract |

Tests for any of the above go in the matching `tests/test_<module>.py`, using the fixture chain
above.

For the layering rules those destinations follow, read [the architecture page](./architecture.md).

## Spec Kit command definitions are locally patched

`.omp/commands/speckit.*.md` are vendored Spec Kit prompt definitions, installed by `specify` and
pinned by checksum in `.specify/integrations/omp.manifest.json`. Upstream, the hook sections require
an agent to invoke any *mandatory* hook automatically, taking the command id from
`.specify/extensions.yml`. That file is repository-controlled, so upstream's behaviour lets an
untrusted checkout direct an agent to run an arbitrary command with the agent session's authority.

The committed copies are patched to close that path: a hook command is never invoked without
explicit user approval, and only an allowlist stored **outside** the checkout may pre-approve one.
The manifest checksums were regenerated to match the patched files, so the tree is self-consistent.

Re-running `specify init` in this repository will restore the upstream text and drop the patch. If
you upgrade the scaffold, re-apply it and regenerate the checksums, or the repository ships an
automatic-execution path again. This project defines no hooks: there is no `.specify/extensions.yml`
and none is expected.
