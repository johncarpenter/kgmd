# Implementation Plan: Corpus Exclusions via `.kgmdignore`

**Branch**: `002-kgmdignore-exclusions` | **Date**: 2026-08-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-kgmdignore-exclusions/spec.md`

## Summary

Add a gitignore-style `.kgmdignore` file at the corpus root that subtracts paths from ingest, and
make the file set shrinking actually shrink the graph.

Three parts, in dependency order:

1. **`kgmd/ignore.py`** — a new stdlib-only leaf module that parses `.kgmdignore` into ordered rules
   and answers `is_ignored(rel_path, rules)`. Patterns are compiled to `re.Pattern` at parse time
   because both stdlib candidates are provably wrong: `fnmatch`'s `*` crosses `/`, and
   `PurePath.match` is right-anchored with single-segment `**` on the supported runtimes
   (`full_match` is 3.13+, the floor is 3.10). Verified by probe — see [research.md](./research.md)
   §R1. No new runtime dependency.
2. **`ingest.scan_corpus_files`** — one function that resolves the file set with fixed precedence
   (`corpus.include` scopes → `.kgmdignore` subtracts, negations re-add → dot-path rule last and
   non-overridable) and returns the included, ignored, and dot-path groups. Both ingest and the
   preview read it, so the preview cannot drift from what a build does.
3. **`ingest.prune_missing_documents`** — removes indexed documents whose path is absent from the
   resolved set. One mechanism covers newly-ignored, deleted, and renamed files. It must clear the
   two `sqlite-vec` tables explicitly: `chunks.id` and `entity_mentions.id` are plain
   `INTEGER PRIMARY KEY` so ids are reused, and `embed_new_chunks` selects
   `WHERE c.id NOT IN (SELECT chunk_id FROM vec_chunks)` — a stale vector row makes a *future,
   unrelated* chunk look already-embedded and search then answers from deleted text. It must also
   delete relations bound to removed evidence, because `relations.evidence_chunk_id` is
   `ON DELETE SET NULL` and those rows would otherwise survive with no provenance.

Surfaces: `kgmd build --dry-run [--json]` previews the resolved set without touching the graph;
`kgmd init` writes a fully-commented starter `.kgmdignore`. No new config key — the ignore file is
the only mechanism, which also keeps `DEFAULT_CONFIG` and the configuration reference's key count
untouched.

Guard added beyond the issue: an ignore ruleset that resolves to an empty set while the graph holds
documents raises before any write. Unconditional pruning makes a stray `*` destructive, and silently
emptying a graph is a worse failure than the one being fixed.

## Technical Context

**Language/Version**: Python `>=3.10`; supported matrix 3.10 / 3.11 / 3.12 / 3.13. No language
feature newer than 3.10 — which is precisely why `PurePath.full_match` (3.13) is unavailable.

**Primary Dependencies**: none added. Existing runtime set unchanged (`click`, `rich`, `pyyaml`,
`platformdirs`, `litellm`, `fastembed`, `sqlite-vec`, `networkx`, `fastmcp`). `pathspec` was
considered and rejected — [research.md](./research.md) §R1.

**Storage**: the single SQLite artifact `.kgmd/graph.db`. **No DDL change, no
`PRAGMA user_version` bump** — this feature only deletes rows from existing tables. New user-authored
input file `<corpus root>/.kgmdignore`, which is configuration rather than corpus state.

**Testing**: `pytest`, function style, `tests/conftest.py` fixture chain
(`tmp_corpus` → `initialized_corpus` → `db_conn` / `seeded_db`). Two new modules:
`tests/test_ignore.py` (pure pattern semantics, no filesystem) and `tests/test_ingest.py` (discovery,
pruning, guard, stale-vector regression). Vectors are hand-packed `struct.pack` rows; no embedding
backend and no network.

**Target Platform**: local CLI plus the MCP stdio server, on macOS and Linux. Patterns always use `/`
regardless of host separator.

**Project Type**: single flat Python package `kgmd/` with a `click` CLI. One new module, no new
subpackage.

**Performance Goals**: SC-004 — the resolved file set is reportable in under 5 seconds on a 1,000-file
corpus. Rule matching is a compiled regex per rule per candidate path; discovery cost stays the
existing `rglob` walk.

**Constraints**: no new runtime dependency; offline-deterministic tests; documentation in the same
change (the docs gate is bidirectional and there is no follow-up window); `ruff` `line-length = 100`,
lint select `E,F,I,W`.

**Scale/Scope**: ~5 source files touched (`kgmd/ignore.py` new, `kgmd/ingest.py`, `kgmd/cli.py`, plus
2 new test modules), and 6 documentation pages — 5 of which contain statements this change
*falsifies*, enumerated in [research.md](./research.md) §R11.

## Constitution Check

*GATE: evaluated before Phase 0, re-evaluated after Phase 1. Both passes recorded.*

### Pass 1 — before Phase 0 research

| Principle | Verdict | Reasoning |
|---|---|---|
| **I. Single durable artifact, versioned schema** | PASS with a question to resolve | No DDL, no new table, no sidecar store; only `DELETE` on existing tables. `.kgmdignore` is a new file outside `graph.db` — must confirm it is *input*, not *state*. Deletes must go through `db.py::get_connection` and run under `build_lock`. |
| **II. Deterministic, mockable LLM boundary** | PASS | Ingest and discovery make no provider call. Nothing added near `call_structured`; no prompt asset changes. |
| **III. Dual-surface parity over one query layer** | OPEN | A new user-visible read (the preview) needs either both surfaces or a stated exclusion, and Principle III ties CLI query commands to `kgmd/query.py`. Resolve in Phase 0. |
| **IV. Content-hash incrementality, idempotent re-runs** | OPEN | Pruning is a new mutation on every build. Must not disturb hash-based skip decisions, must be idempotent, must not be timestamp-driven, and needs an idempotency test in the shape of `test_extraction_idempotent`. |
| **V. Offline-deterministic test gate** | PASS | All new behavior is filesystem and SQL; testable with `tmp_path` and hand-packed vectors. New capability ships tests in the same change. |
| **Tech constraints** | OPEN | New runtime dependency requires justification — decide `pathspec` vs stdlib in Phase 0. New module must not break the one-way dependency direction and must not create a subpackage. Every new config key must be consumed and documented — avoidable only by adding none. |
| **Docs as contract** | PASS, with work | New CLI options and behavior changes must land with docs, verified bidirectionally by `tests/test_docs.py`. |

No violation. Two OPEN items (III, IV) and one dependency question routed to Phase 0.

### Pass 2 — after Phase 1 design

| Principle | Verdict | Evidence |
|---|---|---|
| **I. Single durable artifact** | PASS | No DDL; `user_version` untouched. Pruning runs on the existing connection inside `ingest_documents`, which both call sites already wrap in `build_lock` (`kgmd/cli.py:214` for `build`, `:282` for `extract`). `.kgmdignore` is user-authored *input*, the same class as `.kgmd/config.yaml`, so no corpus state is added outside `graph.db`. Id batching uses chunked `IN (...)` lists specifically to avoid a `TEMP TABLE`, which would be DDL outside `kgmd/schema.py`. |
| **II. Deterministic LLM boundary** | PASS | Unchanged. No module in this change imports `litellm` or `kgmd/llm.py`. `kgmd/induce.py` — the recorded deviation — is not touched. |
| **III. Dual-surface parity** | PASS with stated exclusion | The preview is CLI-only, and the reason is recorded in [contracts/cli-build-dry-run.md](./contracts/cli-build-dry-run.md): the resolved file set is **not graph state**, so `query.py` (the sole read layer for the *graph*) gains no function and discovery stays in `ingest.py`; and the preview answers a pre-spend operator question, whereas MCP tools serve assistants reading committed graph state. `--json` satisfies the machine-output rule. Failures use `click.ClickException` with remediation, human output to `console`, diagnostics to `err_console`. |
| **IV. Incrementality and idempotency** | PASS | Removal is driven by set difference on `documents.path`, never by `mtime`. The hash-based skip path is untouched: an unchanged, un-ignored document still takes the `content_hash` match branch. Pruning takes an early zero-write exit when no orphans exist, which is the idempotency property; `tests/test_ingest.py` asserts a second run removes nothing and re-extracts nothing. Downstream state is invalidated explicitly rather than left mixed-generation — exactly the rule that forces the vector and relation deletes. |
| **V. Offline-deterministic tests** | PASS | Two new hermetic test modules; `tests/test_ignore.py` needs no filesystem at all. Vectors are hand-packed `struct.pack` rows. `tests/fixtures/*.md` is not edited, so no exact-count assertion moves. |
| **Tech constraints** | PASS | Zero new runtime dependencies — the stdlib decision is evidence-backed in [research.md](./research.md) §R1. `kgmd/ignore.py` is a module, not a subpackage, and imports nothing from `kgmd`, so the one-way direction holds as `ingest` → `ignore` → nothing. Connection and config stay parameters; no module-level mutable state. `FileScan` and `IgnoreRule` are `@dataclass`, matching `ingest.Chunk`; pydantic stays reserved for the LLM boundary. **No config key added**, so the "every tunable must be consumed and documented" rule is satisfied vacuously and the reference's key count is unchanged. |
| **Docs as contract** | PASS, with work enumerated | [research.md](./research.md) §R11 lists 7 statements this change falsifies and 5 additions, including the two doc-gate obligations that adding `--json` to `build` creates (`test_all_parameters_documented`, `test_structured_output_parity`) and the exact-literal requirement for the troubleshooting quote (`test_quoted_errors_exist_in_source`). |

**Result: PASS. Complexity Tracking table stays empty — no principle is violated.**

Two recorded constitutional deviations are checked for contact:

- `kgmd/induce.py` bypassing `call_structured` — not touched.
- `llm.max_tokens` split between `config.py` (16384) and `extract.py` (4096) — neither module is
  touched by this change, so the "reconcile when next touched" obligation is not triggered. Left as
  recorded debt rather than silently widening scope.

One adjacent defect is deliberately **not** fixed: `kgmd reset` and `reset --hard` also fail to clear
the vec tables (`kgmd/cli.py:674-688`), and `reset` is separately broken by `VACUUM` inside a
transaction. Both are documented in `docs/guides/maintenance.md` and neither is in this feature's
scope; fixing `reset` here would be unrequested scope. The prune path introduced here does clear
vectors, so this change does not add to that debt.

## Project Structure

### Documentation (this feature)

```text
specs/002-kgmdignore-exclusions/
├── plan.md                          # This file
├── spec.md                          # Feature specification
├── research.md                      # Phase 0 — 12 decisions, probe-verified
├── data-model.md                    # Phase 1 — structures, tables, removal ordering
├── quickstart.md                    # Phase 1 — runnable validation scenarios
├── contracts/
│   ├── kgmdignore-format.md         # The user-authored file format (public contract)
│   ├── cli-build-dry-run.md         # New CLI flags + JSON shape
│   └── library-api.md               # Function signatures and error contract
├── checklists/
│   └── requirements.md              # Spec quality checklist (16/16)
└── tasks.md                         # Phase 2 — created by /speckit.tasks, NOT here
```

### Source Code (repository root)

```text
kgmd/
├── ignore.py          # NEW — parse/compile/match .kgmdignore; starter template + writer
├── ingest.py          # CHANGED — FileScan, scan_corpus_files, prune_missing_documents
├── cli.py             # CHANGED — build --dry-run/--json; init writes starter .kgmdignore
├── config.py          # UNCHANGED — no new config key (FR-020)
├── schema.py          # UNCHANGED — no DDL change
├── embed.py           # UNCHANGED — but its NOT IN (SELECT chunk_id FROM vec_chunks)
│                      #   query is why vector cleanup is mandatory
├── db.py · query.py · extract.py · resolve.py · induce.py · export.py · mcp_server.py
└── prompts/           # UNCHANGED

tests/
├── test_ignore.py     # NEW — pattern semantics, pure unit tests
├── test_ingest.py     # NEW — discovery, pruning, guard, stale-vector regression
├── conftest.py        # UNCHANGED — existing fixture chain is sufficient
├── fixtures/*.md      # UNCHANGED — golden corpus, alias variants preserved
└── test_docs.py       # UNCHANGED — but gates every doc edit below

docs/
├── reference/cli.md              # build: --dry-run, --json, Structured output block; init: starter file
├── reference/configuration.md    # NEW .kgmdignore section; corpus.include interaction
├── guides/maintenance.md         # spend control; the deleted/renamed rows that are now wrong
├── guides/troubleshooting.md     # empty-resolved-set guard entry
├── examples/personal-notes.md    # "Deleted notes are not removed" limitation is gone
├── examples/mcp-assistant.md     # stale claim about deleted notes
└── contributing/architecture.md  # ingest.py row: name the ignore pass and scan_corpus_files
```

**Structure Decision**: the existing flat `kgmd/` package with one added leaf module. `kgmd/ignore.py`
holds pattern parsing, matching, and the starter-file template — ~60 lines of translation logic with
a dense unit-test surface that would otherwise be half of `ingest.py`. It imports stdlib only, so the
constitution's dependency direction extends cleanly as `ingest` → `ignore` → nothing. No subpackage
is created (prohibited for code), and `.kgmdignore` lives at the corpus root beside the user's notes
because it is version-controllable input, not derived state.

## Phase Outputs

| Phase | Status | Artifacts |
|---|---|---|
| 0 — Outline & Research | Complete | [research.md](./research.md) — R1…R12, all decisions probe- or source-verified; zero unresolved unknowns |
| 1 — Design & Contracts | Complete | [data-model.md](./data-model.md), [contracts/](./contracts/) ×3, [quickstart.md](./quickstart.md) |
| 2 — Tasks | Not started | `tasks.md` — produced by `/speckit.tasks` |

### Suggested implementation order

Derived from the dependency graph, not from the story priorities — story P1 needs items 1–3, P2 needs
4, P3 needs 5:

1. `kgmd/ignore.py` + `tests/test_ignore.py` — pure, no dependants yet.
2. `ingest.scan_corpus_files` + `FileScan`, composing the unchanged `find_markdown_files` and
   `_is_dotpath`; point `ingest_documents` at it. Assert the no-ignore-file path is unchanged first.
3. `tests/test_ingest.py` discovery cases, including the `corpus.include` interaction and dot-path
   non-overridability.
4. `ingest.prune_missing_documents` + the empty-set guard, wired into `ingest_documents` before its
   insert/update loop; pruning, idempotency, and stale-vector tests.
5. `kgmd build --dry-run [--json]` before `init_db`; `kgmd init` starter file.
6. Documentation — the 5 falsified statements first, then the 5 additions. Run `make test` to let
   `tests/test_docs.py` prove both directions.

## Risks

| Risk | Mitigation |
|---|---|
| Pruning silently deletes a graph on a bad pattern | FR-015 guard raises before any write; dry run makes rules inspectable first |
| Stale vectors bind to reused ids | Explicit deletes from both vec tables before the chunk delete; regression test asserts the row is gone |
| Preview drifts from real build behavior | Single `scan_corpus_files` feeds both; no second code path exists |
| Entity sweep removes more than intended | Scoped to entities whose mentions this prune removed; pre-existing orphans left as recorded debt |
| Doc gate fails late in the change | The falsified statements are enumerated with line numbers in research.md §R11 rather than discovered by a red suite |

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified.

No violations. Table intentionally empty.
