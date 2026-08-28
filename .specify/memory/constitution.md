<!--
AMENDMENT 1.0.0 → 1.1.0 (2026-08-28)
Bump rationale: MINOR. Existing guidance materially expanded; no principle removed or redefined.
Change: Development Workflow & Quality Gates → "Documentation as contract" now names two
documentation surfaces (`README.md` for orientation, `docs/` for authoritative depth) instead of
`README.md` alone, and requires surface coverage to be mechanically verifiable in both directions.
Driver: specs/001-project-documentation (FR-003, FR-040, FR-041); plan.md Complexity Tracking row 1.
Templates requiring no edit: plan-template.md, spec-template.md, tasks-template.md,
checklist-template.md (all read the constitution at runtime).

---

SYNC IMPACT REPORT
Version change: (unfilled template) → 1.0.0
Bump rationale: MAJOR/initial ratification. The prior file was the unpopulated core scaffold with
zero project values, so this is the first governing version rather than an amendment.

Modified principles: none renamed (no prior named principles existed).
Added sections:
  - Core Principles I–V (Single Durable Artifact; Deterministic LLM Boundary; Dual-Surface Parity;
    Content-Hash Incrementality; Offline-Deterministic Test Gate)
  - Technology & Configuration Constraints
  - Development Workflow & Quality Gates
  - Governance
Removed sections: none (all template placeholder slots populated).

Templates / commands requiring no edit (read constitution at runtime):
  - .specify/templates/plan-template.md ("Constitution Check" gate, Complexity Tracking table)
  - .specify/templates/spec-template.md, tasks-template.md, checklist-template.md

Follow-up TODOs: none. Ratification date is the date of first adoption of this document.

Known deviations recorded, not waived, at time of ratification (see Principle II and
Technology & Configuration Constraints):
  - kgmd/induce.py calls litellm directly instead of kgmd/llm.py::call_structured.
  - config keys extraction.max_entities_per_chunk, extraction.max_relations_per_chunk,
    induction.include_attribute_summary are declared but never consumed.
  - llm.max_tokens default diverges: 16384 in kgmd/config.py vs 4096 in kgmd/extract.py.
  - `ruff format` is a Makefile target but is not enforced in CI.
-->

# kgmd Constitution

## Core Principles

### I. Single Durable Artifact, Versioned Schema (NON-NEGOTIABLE)

All corpus state MUST live in one SQLite file at `.kgmd/graph.db`. No sidecar databases, pickles,
JSON caches, or per-stage state files may be introduced.

- All DDL MUST reside in `kgmd/schema.py` (`SCHEMA_SQL`, `vec_tables_sql`, `KV_DEFAULTS`). Modules
  MUST NOT issue `CREATE TABLE` outside that module.
- Every connection MUST be obtained from `kgmd/db.py::get_connection`, which loads `sqlite-vec` and
  sets `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`. Ad hoc `sqlite3.connect` in
  library or CLI code is PROHIBITED.
- `init_db` creates the schema only when `PRAGMA user_version == 0`. Any DDL change MUST either ship
  a migration branch that raises `user_version`, or fail fast with an actionable remediation message
  in the style of `check_embedding_model` ("delete `.kgmd/graph.db` and rebuild"). Silently mutating
  an existing database is PROHIBITED.
- Operations that mutate corpus state MUST run inside `db.py::build_lock` (fcntl PID lock on
  `.kgmd/build.lock`). Concurrent writers within a stage MUST serialize on an explicit lock, as
  `kgmd/extract.py` does around its `ThreadPoolExecutor`.

Rationale: the product promise is "one file you can delete." Provenance, incrementality, and
crash-safety all depend on exactly one authoritative store with a declared version.

### II. Deterministic, Mockable LLM Boundary

Every LLM interaction MUST be routed through `kgmd/llm.py::call_structured` and MUST be
reproducible and stubbable at a single patch point.

- `temperature` MUST default to `0.0`; structured calls MUST request JSON object output, validate
  against a pydantic model from `kgmd/schema.py`, and retry only for parse/validation failure within
  the configured `extraction.retry_on_parse_failure` bound.
- Prompts MUST be shipped as text assets under `kgmd/prompts/` and MUST remain overridable per
  corpus from `.kgmd/prompts/`. Inline prompt string literals in logic modules are PROHIBITED.
- Logs MUST record call metadata only (model, sizes, elapsed) to `.kgmd/logs/build.log`. Writing
  prompt or response bodies, or any credential, to disk is PROHIBITED.
- New LLM-backed stages MUST NOT bypass `call_structured`. `kgmd/induce.py` currently calls
  `litellm.completion` directly because it parses YAML rather than JSON; this is a recorded
  deviation, and any change to that module MUST either converge it onto the shared wrapper or
  restate the justification in the plan's Complexity Tracking table.

Rationale: a single deterministic boundary is what makes the pipeline testable offline and makes
extraction results comparable across runs.

### III. Dual-Surface Parity Over One Query Layer

`kgmd/query.py` is the sole read layer. The CLI (`kgmd/cli.py`) and the MCP server
(`kgmd/mcp_server.py`) are thin presentation shells over it.

- SQL, vector search, and graph traversal MUST NOT be duplicated in `cli.py` or `mcp_server.py`;
  both MUST call `kgmd/query.py` functions, which return plain dicts.
- Every read-oriented CLI command MUST offer machine output via `--json`
  (`is_flag`, dest `as_json`) in addition to its rich human rendering.
- User-facing failures MUST be raised as `click.ClickException` with a remediation hint (for
  example "Run 'kgmd init' first"). Human output goes to the rich `Console`; errors and diagnostics
  go to the stderr console. Bare tracebacks MUST reach the user only under the global `--debug`
  flag.
- Adding an MCP tool or a CLI query command REQUIRES a corresponding `kgmd/query.py` function; new
  capability MUST reach both surfaces or the plan MUST state why one surface is excluded.

Rationale: CLI and MCP answering differently for the same graph is a correctness bug; one read
layer makes divergence structurally impossible.

### IV. Content-Hash Incrementality and Idempotent Re-Runs

`kgmd build` MUST be safe and cheap to re-run. Skip decisions MUST be derived from content digests,
never from timestamps.

- Ingest skips a document only when `sha256` of its content matches `documents.content_hash`;
  extraction skips only when `documents.last_extracted_hash` matches the current hash. `mtime` MAY
  be stored but MUST NOT drive skip decisions.
- Changed content MUST invalidate downstream state explicitly (clear `last_extracted_hash`, delete
  stale chunks) rather than leaving mixed-generation rows.
- Extraction watermarks MUST advance only after a successful chunk, so an interrupted or failed run
  never marks work as done.
- `--force` MUST remain the only way to bypass incrementality. Every stage that gains a skip path
  MUST add an idempotency test in the shape of
  `tests/test_extract.py::test_extraction_idempotent`.

Rationale: users re-run builds on large corpora against paid LLM APIs; a wrong skip silently
corrupts the graph and a missing skip silently costs money.

### V. Offline-Deterministic Test Gate (NON-NEGOTIABLE)

The suite MUST pass with no network access, no model downloads, and no wall-clock or ordering
sensitivity.

- LLM access MUST be mocked at the `litellm.completion` seam. Embedding backends MUST NOT be
  invoked in tests; vectors are hand-packed `struct.pack(f"{dim}f", ...)` float32 rows inserted
  into the `sqlite-vec` tables.
- Tests MUST use `pytest` function style and the `tests/conftest.py` fixture chain
  (`tmp_corpus` → `initialized_corpus` → `db_conn` / `seeded_db`). Filesystem use MUST be
  `tmp_path` or `Path(__file__).parent`; absolute paths, `time.sleep`, and unseeded randomness are
  PROHIBITED.
- `tests/fixtures/*.md` is the golden corpus and MUST keep its deliberate alias variants (for
  example "Sarah Chen" / "Dr. Chen" / "S. Chen") because entity-resolution behavior depends on
  them. Editing fixtures REQUIRES updating the exact-count assertions that depend on them.
- Every new pipeline stage, query function, export format, MCP tool, or CLI command MUST ship
  tests in the same change. Deleting or skipping a failing test in place of fixing it is
  PROHIBITED.

Rationale: the whole product wraps a nondeterministic paid API; the test suite is only useful if it
is fast, free, and hermetic.

## Technology & Configuration Constraints

- **Runtime**: Python `>=3.10`, with 3.10 / 3.11 / 3.12 / 3.13 all supported. Language features
  newer than 3.10 are PROHIBITED. Dependencies are declared in `pyproject.toml` with lower bounds;
  adding a runtime dependency REQUIRES justification in the plan, since `sqlite-vec` and
  `fastembed` already impose non-trivial install constraints.
- **Package layout**: one flat package `kgmd/`. New subpackages are PROHIBITED except for
  non-code assets (`kgmd/prompts/`). Dependency direction MUST stay one-way:
  `cli.py` / `mcp_server.py` → `query` / `ingest` / `extract` / `resolve` / `induce` / `export` →
  `llm` / `embed` / `db` → `schema`. Nothing may import `cli.py`.
- **Dependency injection**: `sqlite3.Connection` and the config dict MUST be passed as arguments.
  Module-level mutable globals are PROHIBITED apart from the rich consoles and the `FastMCP`
  instance.
- **Data contracts**: pydantic models are reserved for LLM input/output validation in
  `kgmd/schema.py`. Internal transfer uses plain dicts and `@dataclass` (for example
  `ingest.Chunk`). Public functions MUST carry type hints.
- **Configuration**: config is a plain nested dict with precedence
  `DEFAULT_CONFIG` → global `platformdirs` `~/.config/kgmd/config.yaml` → corpus
  `.kgmd/config.yaml`, deep-merged. Every new tunable MUST be added to `DEFAULT_CONFIG`, actually
  consumed by code, and documented in `README.md`. Declared-but-unconsumed keys are a defect;
  `extraction.max_entities_per_chunk`, `extraction.max_relations_per_chunk`, and
  `induction.include_attribute_summary` are recorded as existing debt to be either wired up or
  removed. Defaults MUST NOT be restated with a different value at the call site; the current
  `llm.max_tokens` split (16384 in `config.py` vs 4096 in `extract.py`) MUST be reconciled when
  either module is next touched.
- **Secrets**: `kgmd` MUST NOT read, prompt for, log, or persist API keys. Provider credentials are
  environment variables consumed implicitly by `litellm`. Embeddings default to local `fastembed`
  so the tool remains usable with no embedding credentials.
- **Embedding immutability**: `kv.embedding_model` and `kv.embedding_dim` are fixed at
  initialization. Mismatches MUST raise via `check_embedding_model`; silent re-embedding is
  PROHIBITED.
- **Style**: `ruff` with `line-length = 100`, `target-version = "py310"`, lint select
  `["E", "F", "I", "W"]`. These settings are the single source of formatting truth; competing
  formatter or linter configs MUST NOT be added.

## Development Workflow & Quality Gates

- **Canonical commands** are the `Makefile` targets: `make install` (`pip install -e ".[dev]"`),
  `make test` (`python -m pytest tests/ -v`), `make lint` (`ruff check kgmd/ tests/`),
  `make format` (`ruff format` then `ruff check --fix`), `make build` (`python -m build`),
  `make clean`. Contributors MUST use these rather than bespoke invocations.
- **Pre-submit gate**: `make format`, `make lint`, and `make test` MUST all be clean locally before
  a change is proposed.
- **CI gate (blocking)**: `.github/workflows/ci.yml` runs `ruff check .` then `pytest -v` on the
  full 3.10–3.13 matrix for every push and pull request to `main`. Merging with a red matrix leg is
  PROHIBITED. Bypassing hooks or checks (for example `git commit --no-verify`) is PROHIBITED.
  Because CI enforces `ruff check` but not `ruff format`, formatting drift MUST be caught by
  `make format` before submission.
- **Trunk**: `main` is the only long-lived branch and MUST remain releasable.
- **Release**: bump `__version__` in `kgmd/__init__.py` (the hatch dynamic version source), then
  publish a GitHub Release. `.github/workflows/publish.yml` builds and uploads to PyPI via OIDC
  trusted publishing in the `pypi` environment. Manual `twine upload`, committed API tokens, and
  out-of-band artifact uploads are PROHIBITED.
- **Commit messages**: capitalized imperative subject lines describing the why (matching existing
  history, for example "Fix lint errors and add CI/CD workflows"). Conventional Commit prefixes are
  not used.
- **Documentation as contract**: any new or changed CLI command, MCP tool, config key, export
  format, or install requirement MUST update the documentation in the same change. Two surfaces
  carry this obligation: `README.md` is the orientation surface and the PyPI landing page, and
  `docs/` is the authoritative depth surface (reference, guides, examples, contributor material).
  Where the two overlap, `docs/` wins for detail and `README.md` links into it rather than
  duplicating it. Surface coverage MUST be mechanically verifiable — a command, option, config key,
  MCP tool, or export format with no documentation entry, and a documented entry naming something
  that does not exist, MUST both fail the test gate.
- **Spec Kit flow**: planning artifacts live under `.specify/`. `.specify/templates/plan-template.md`
  MUST evaluate its "Constitution Check" gate against these principles before Phase 0 research and
  again after Phase 1 design.

## Governance

This constitution supersedes ad hoc practice, habit, and undocumented convention. Where this
document and a code comment, README passage, or reviewer preference conflict, this document wins
until it is amended.

- **Amendment procedure**: amendments are proposed as a pull request that edits only
  `.specify/memory/constitution.md`, states the rationale, sets the new version and
  `Last Amended` date, and updates the Sync Impact Report comment at the top of the file. An
  amendment that invalidates existing code MUST name the affected modules and the migration path.
  Template and command files are not edited by an amendment; they read this file at runtime.
- **Versioning policy** (semantic, for this document):
  - **MAJOR**: a principle is removed or redefined in a backward-incompatible way, or governance
    itself changes.
  - **MINOR**: a principle or section is added, or existing guidance is materially expanded.
  - **PATCH**: clarification, wording, or typo fixes with no change in obligation.
- **Compliance review**: every pull request review MUST verify the principles that the change
  touches — schema/versioning (I), LLM boundary (II), CLI/MCP parity (III), incrementality (IV),
  and test hermeticity (V). Reviewers MUST reject changes that add state outside `graph.db`, bypass
  `call_structured`, duplicate query logic in a surface module, or introduce network access into the
  test suite.
- **Justified complexity**: a change may violate a principle only by recording the violation, the
  reason it is needed, and the rejected simpler alternative in the Complexity Tracking table of
  `.specify/templates/plan-template.md`. Undocumented violations MUST be reverted.
- **Recorded deviations**: the deviations listed in the Sync Impact Report are acknowledged debt,
  not grants of permission. Touching the affected code REQUIRES either fixing the deviation or
  re-justifying it.

**Version**: 1.1.0 | **Ratified**: 2026-08-28 | **Last Amended**: 2026-08-28
