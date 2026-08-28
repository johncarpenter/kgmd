---

description: "Task list for Corpus Exclusions via .kgmdignore"
---

# Tasks: Corpus Exclusions via `.kgmdignore`

**Input**: Design documents from `/specs/002-kgmdignore-exclusions/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: REQUIRED, not optional. Constitution Principle V ("Every new pipeline stage, query
function, export format, MCP tool, or CLI command MUST ship tests in the same change"), spec SC-007,
and the source issue's acceptance criteria ("verified by a test asserting the discovered file set")
all demand them. Repo convention is TDD — test red, then implement green.

**Organization**: Tasks are grouped by user story so each story is independently implementable and
independently testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel — different files, no dependency on an incomplete task
- **[Story]**: US1 / US2 / US3, mapping to the prioritized stories in [spec.md](./spec.md)
- Exact file paths are in every task

## Path Conventions

Single flat Python package at the repository root: `kgmd/` for source, `tests/` for tests, `docs/`
for the authoritative documentation surface. No `src/` directory. Per
[plan.md](./plan.md) → Project Structure.

## Critical constraints that shape these tasks

1. **Documentation is gated per story, not deferred to Polish.** `tests/test_docs.py` fails the whole
   suite in both directions, so a story whose docs are missing leaves a red suite. Each story phase
   therefore carries its own documentation tasks and each checkpoint is genuinely green.
2. **Same-file tasks are never `[P]`.** `kgmd/ingest.py`, `kgmd/cli.py`, and `tests/test_ingest.py`
   are each touched by several phases; those tasks are sequential by construction.
3. **Collect ids before deleting.** In pruning, mention ids are unrecoverable once chunks are gone —
   see [data-model.md](./data-model.md) §3 for the exact 12-step order.
4. **No new runtime dependency, no DDL, no new config key.** If a task seems to need one, stop: the
   design says it does not.

---

## Phase 1: Setup

**Purpose**: Establish an attributable baseline before touching anything.

- [X] T001 Run `make format && make lint && make test` on the unmodified tree and record the passing test count, so every later failure is attributable to this change rather than to pre-existing state

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Introduce the single resolved-file-set function that all three stories read. This phase
deliberately adds **no** new behavior — it is a pure refactor whose success criterion is that nothing
changes.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 [P] Write failing test in `tests/test_ingest.py` asserting `scan_corpus_files(corpus, config)` returns a `FileScan` whose `included` equals the current `sorted(root.rglob("*.md"))` minus dot-paths over `tests/fixtures/`, whose `ignored` is empty with no `.kgmdignore` present, and whose three lists are disjoint (spec FR-009, SC-003)
- [X] T003 Add the frozen `FileScan` dataclass (`included`, `ignored`, `dotpath`: `list[Path]`) and `scan_corpus_files(root, config) -> FileScan` to `kgmd/ingest.py`, composing the **unchanged** `find_markdown_files` and `_is_dotpath` with an empty ignore stage, per [contracts/library-api.md](./contracts/library-api.md)
- [X] T004 Replace the inline discovery-and-dot-path filter in `ingest_documents` (`kgmd/ingest.py`, currently lines 160-163) with a `scan_corpus_files` call, leaving the insert/update loop and the returned `new`/`updated`/`skipped`/`chunks_created` keys untouched
- [X] T005 Verify no behavior change: run `python -m pytest tests/ -v` and confirm the same passing count as T001, with `tests/test_extract.py` (which calls `ingest_documents` three times) green

**Checkpoint**: One function now answers "what would this corpus index". All three stories can begin.

---

## Phase 3: User Story 1 - Exclude a folder from indexing (Priority: P1) 🎯 MVP

**Goal**: A `.kgmdignore` file at the corpus root subtracts paths from ingest, with comments, blank
lines, directory rules, globs, and negation — and the dot-path rule still cannot be overridden.

**Independent Test**: Create a temporary corpus with files inside and outside the ignored paths, add
a `.kgmdignore`, and assert the resolved file set is exactly the expected paths. No model access, no
network, no database needed.

### Tests for User Story 1

> Write these first and confirm they fail — `kgmd/ignore.py` does not exist yet.

- [X] T006 [P] [US1] Create `tests/test_ignore.py` covering parsing: `#` comments, blank and whitespace-only lines, trailing-whitespace stripping, `!` setting negation, trailing `/` setting directory-only, a lone `!` or `/` producing no rule, and `line_number` being 1-based
- [X] T007 [P] [US1] Extend `tests/test_ignore.py` with matching semantics from [contracts/kgmdignore-format.md](./contracts/kgmdignore-format.md): `*` never crossing `/`, `?` matching one non-`/` character, `**` spanning several segments with `a/**/b` also matching `a/b`, leading-`/` anchoring, interior-`/` anchoring, no-`/` matching at any depth, directory rules covering the whole subtree, last-match-wins ordering, negation re-including a file inside an excluded directory, `is_ignored(path, [])` always `False`, and an unsupported `[a-z]` class matching literally rather than excluding
- [X] T008 [P] [US1] Add ignore-integration cases to `tests/test_ingest.py`: the worked example from the format contract resolving exactly as tabulated, `corpus.include` plus `.kgmdignore` together (ignore subtracts from the allowlist), a file matched by a rule but already outside `corpus.include` causing no error, `!.kgmd/notes.md` failing to re-admit a dot-path (FR-008), an empty/comments-only `.kgmdignore` behaving as no rules, and an undecodable `.kgmdignore` raising with the filename in the message

### Implementation for User Story 1

- [X] T009 [US1] Create `kgmd/ignore.py` with the frozen `IgnoreRule` dataclass and `parse_ignore_rules(text) -> list[IgnoreRule]`, compiling each pattern to a fully anchored `re.Pattern` at parse time — stdlib only (`dataclasses`, `pathlib`, `re`), importing nothing from `kgmd`
- [X] T010 [US1] Add `load_ignore_rules(root)` (returns `[]` when `.kgmdignore` is absent; raises `RuntimeError` naming the file when present and undecodable) and `is_ignored(rel_path, rules)` (tests every rule against the path and each ancestor prefix, last match wins) to `kgmd/ignore.py`
- [X] T011 [US1] Wire the ignore stage into `scan_corpus_files` in `kgmd/ingest.py`: load rules once per call, partition candidates into `ignored` and survivors, then apply `_is_dotpath` **last** so no negation can reach the dot-path decision
- [X] T012 [US1] Add `DEFAULT_IGNORE_TEMPLATE` (every line a comment or blank, with worked examples for directory, glob, and negation rules) and `write_default_ignore_file(path)` (no-op when the file exists, so a user's file is never clobbered) to `kgmd/ignore.py`
- [X] T013 [US1] Call `write_default_ignore_file(corpus_dir / ".kgmdignore")` from `init` in `kgmd/cli.py` (after `write_default_config`, around line 91) and print the path alongside the existing Database/Config lines
- [X] T014 [US1] Add a test to `tests/test_ingest.py` asserting the starter template parses to zero rules, so a freshly initialized corpus indexes exactly what it indexes today (FR-019)

### Documentation for User Story 1

- [X] T015 [P] [US1] Add a `.kgmdignore` section to `docs/reference/configuration.md` covering location, line grammar, the supported constructs table, precedence, the deliberate git divergence on negation inside an excluded directory, and the unsupported constructs — sourced from [contracts/kgmdignore-format.md](./contracts/kgmdignore-format.md)
- [X] T016 [P] [US1] Update the `corpus.include` row in `docs/reference/configuration.md` (line 78) to state the interaction: the allowlist scopes the walk, `.kgmdignore` subtracts from it, and the dot-path rule applies last — without adding a config key, so the page's "Nineteen keys" count stays correct
- [X] T017 [P] [US1] Add `.kgmdignore` to `docs/guides/maintenance.md` under "Controlling provider spend" (line 89), stating that excluded files cost nothing because spend is per chunk, and that `corpus.include` scopes the walk while `.kgmdignore` controls spend
- [X] T018 [P] [US1] Note the starter `.kgmdignore` in the `### init` section of `docs/reference/cli.md` (line 45), including that an existing file is never overwritten

**Checkpoint**: Exclusion works end to end. `make test` is green, docs are consistent, and this is a
shippable MVP for any corpus built after the ignore file exists.

---

## Phase 4: User Story 2 - Newly-excluded material leaves the graph (Priority: P2)

**Goal**: Documents absent from the resolved set — newly ignored, deleted, or renamed — are removed
from the graph along with their chunks, mentions, evidence-bound relations, vectors, and any entity
left with no mention and no relation.

**Independent Test**: Build a graph over a seeded corpus, add an ignore rule covering one document,
re-run ingest, and assert that document and everything derived from it is gone while untouched
documents are unchanged. Works without US1 as well, by deleting a file instead of ignoring it.

### Tests for User Story 2

> Write these first. Use hand-packed `struct.pack` vectors per Principle V — no embedding backend.

- [X] T019 [US2] Add prune tests to `tests/test_ingest.py`: after a document's path leaves the resolved set, its `documents` row, its `chunks`, its `entity_mentions`, and its `relations` rows bound to those chunks as evidence are all gone, while a sibling document's rows are untouched
- [X] T020 [US2] Add the stale-vector regression to `tests/test_ingest.py`: insert hand-packed rows into `vec_chunks` and `vec_entity_mentions` for a document's chunks and mentions, remove the document, and assert both vector tables have no row for the removed ids — the failure mode this prevents is `embed_new_chunks` selecting `WHERE c.id NOT IN (SELECT chunk_id FROM vec_chunks)` and treating a reused id as already embedded (`kgmd/embed.py:89-92`)
- [X] T021 [US2] Add the entity-sweep test to `tests/test_ingest.py`: an entity mentioned only in the removed document is deleted, an entity also mentioned elsewhere survives, and an entity that still holds a relation survives (SC-005)
- [X] T022 [US2] Add the idempotency test to `tests/test_ingest.py`, in the shape of `tests/test_extract.py::test_extraction_idempotent`: a second ingest over an unchanged corpus removes nothing, reports zero removal counts, and leaves `documents.last_extracted_hash` intact so no re-extraction is triggered (FR-014, Principle IV)
- [X] T023 [US2] Add the guard test to `tests/test_ingest.py`: with a non-empty graph and an ignore rule matching everything, ingest raises and the `documents`, `chunks`, and vector tables are byte-for-byte unchanged (FR-015) — plus the deleted-file and renamed-file cases, asserting a rename resolves to one removal and one insert in a single transaction

### Implementation for User Story 2

- [X] T024 [US2] Implement `prune_missing_documents(conn, kept_rel_paths) -> dict` in `kgmd/ingest.py` following the ordered sequence in [data-model.md](./data-model.md) §3: resolve orphan document ids, collect chunk ids then mention ids then their entity ids **before** any delete, and take the zero-write early exit when there are no orphans
- [X] T025 [US2] Add the empty-set guard to `prune_missing_documents` before any write: when `kept_rel_paths` is empty and `documents` is non-empty, raise `RuntimeError` in the style of `check_embedding_model` (`kgmd/db.py:50-54`), keeping the leading fragment a single contiguous string literal so `docs/guides/troubleshooting.md` can quote it verbatim, with the document count in a later interpolated fragment
- [X] T026 [US2] Add the delete sequence to `prune_missing_documents`: `vec_entity_mentions` by mention id, `vec_chunks` by chunk id, `relations` by `evidence_chunk_id` (explicit — the column is `ON DELETE SET NULL`, so those rows would otherwise survive with no provenance), `chunks` by document id (cascades mentions), `documents` by id, then the scoped entity sweep; bind ids in batches of 500 and use no `TEMP TABLE`, which would be DDL outside `kgmd/schema.py`
- [X] T027 [US2] Call `prune_missing_documents` from `ingest_documents` in `kgmd/ingest.py` with the resolved corpus-relative paths, before the insert/update loop, and merge the five removal counts into the returned stats dict without renaming any existing key
- [X] T028 [US2] Report the removal counts in `kgmd/cli.py` in both ingest summaries — `build` (line 224) and `extract` (line 286) — so the user sees what left the graph (FR-016)

### Documentation for User Story 2

- [X] T029 [P] [US2] Correct the "Change made, work repeated" table in `docs/guides/maintenance.md` (lines 63-64): "File deleted from disk" now removes the document, its chunks, its mentions, its evidence-bound relations, and its vectors; "File renamed" is now a removal plus an insert with nothing lingering at the old path
- [X] T030 [P] [US2] Update `docs/guides/maintenance.md` lines 42-43 and 86-87 so the orphan-entity statements stay accurate: entities are still never swept on an **edit**, but a document **removal** now sweeps entities it leaves with no mention and no relation; keep the `extract --force` orphan case documented as an open limitation
- [X] T031 [P] [US2] Remove the now-false "**Deleted notes are not removed from the graph.**" limitation from `docs/examples/personal-notes.md` (lines 271-275) and replace it with the new behavior, including the empty-resolved-set guard
- [X] T032 [P] [US2] Fix the stale claim in `docs/examples/mcp-assistant.md` (line 170) that tools reflect "entities extracted from notes you have since deleted"
- [X] T033 [P] [US2] Add a troubleshooting entry to `docs/guides/troubleshooting.md` for the empty-resolved-set guard, with exactly one code span on the `**Symptom**:` line quoting a literal that appears verbatim in `kgmd/ingest.py` — `test_quoted_errors_exist_in_source` enforces this

**Checkpoint**: The file set shrinking now shrinks the graph. US1 and US2 both work independently and
`make test` is green.

---

## Phase 5: User Story 3 - Preview what will be indexed (Priority: P3)

**Goal**: `kgmd build --dry-run` reports the resolved file set, the exclusion counts, and how many
indexed documents would be removed — writing nothing and calling no model. `--json` gives the
machine-readable form.

**Independent Test**: Run the preview against a temporary corpus with an ignore file; assert the
reported set matches expectation, no `graph.db` is created, and the JSON shape matches the contract.

### Tests for User Story 3

- [X] T034 [US3] Add `dry_run_report` tests to `tests/test_ingest.py`: the returned dict matches the shape in [contracts/cli-build-dry-run.md](./contracts/cli-build-dry-run.md), all paths are corpus-relative POSIX strings sorted identically to ingest order, `counts.would_remove` reflects indexed documents absent from `included`, `conn=None` yields `would_remove` of 0, and calling it leaves every table unchanged
- [X] T035 [P] [US3] Create `tests/test_cli.py` using `click.testing.CliRunner` for the two guarantees that only exist at the CLI level: `kgmd build --dry-run` on a corpus with no database creates no `.kgmd/graph.db`, and `kgmd build --json` without `--dry-run` exits non-zero with `--json requires --dry-run.` — this deliberately establishes the CliRunner convention, since no existing test invokes the CLI

### Implementation for User Story 3

- [X] T036 [US3] Implement `dry_run_report(conn, corpus_dir, config) -> dict` in `kgmd/ingest.py`: call `scan_corpus_files`, convert paths to sorted corpus-relative POSIX strings, and count indexed documents absent from `included` by reading `documents.path` (read-only; tolerate `conn=None`)
- [X] T037 [US3] Add `--dry-run` and `--json` (dest `as_json`) options to `build` in `kgmd/cli.py`, rejecting `--json` without `--dry-run` via `click.ClickException`, and handle the dry-run branch **before** `init_db` so no `graph.db` is created — passing a connection only when the database already exists
- [X] T038 [US3] Render the preview in `kgmd/cli.py`: the human form on `console` per the contract's sample output, and `json.dumps` of the report as the only stdout content under `--json`

### Documentation for User Story 3

- [X] T039 [US3] Add `` `--dry-run` `` and `` `--json` `` rows to the parameter table in the `### build` section of `docs/reference/cli.md` (lines 116-121) — `test_all_parameters_documented` requires both as inline code spans in that section
- [X] T040 [US3] Add a `**Structured output**:` block to the `### build` section of `docs/reference/cli.md` documenting the JSON shape — mandatory now that `build` has an `as_json` parameter, because `test_structured_output_parity` compares documented blocks against commands having one
- [X] T041 [US3] Document the dry-run workflow in the `### build` prose of `docs/reference/cli.md`: it takes no build lock, makes no provider call, creates no database, and is the way to check `.kgmdignore` rules before spending

**Checkpoint**: All three stories independently functional; ignore rules are debuggable instead of
guesswork.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T042 [P] Update the `kgmd/ingest.py` row in `docs/contributing/architecture.md` (line 15) to name `scan_corpus_files` as the resolved-file-set entry point, the `.kgmdignore` pass, and `prune_missing_documents`, and add a `kgmd/ignore.py` row placing it as a stdlib-only leaf
- [X] T043 [P] Add one orientation line to `README.md` under Quickstart pointing at `.kgmdignore` and `kgmd build --dry-run` as the spend-control path, linking to `docs/reference/configuration.md` rather than duplicating detail
- [X] T044 Run `make format && make lint` and fix any `ruff` finding (`line-length = 100`, select `E,F,I,W`); do not add a competing formatter config
- [X] T045 Run `make test` and confirm every `tests/test_docs.py` check passes in both directions — no undocumented surface, no documented surface that does not exist
- [X] T046 Walk [quickstart.md](./quickstart.md) Scenarios 1, 2, 3, 4, and 6 (all offline) and confirm each expected outcome; Scenario 5 is optional and costs money
- [X] T047 Confirm the Success Criteria in [spec.md](./spec.md) hold, naming the artifact that proves each: SC-001 and SC-003 via the discovery assertions in `tests/test_ingest.py`, SC-004 by timing `dry_run_report` over a 1,000-file corpus generated in `tmp_path` (throwaway, never committed), SC-005 via the entity-sweep and search assertions in `tests/test_ingest.py`, SC-006 via `tests/test_docs.py`, and SC-007 by running `make test` with no network access

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup — **blocks all three stories**, because every story
  reads `scan_corpus_files`
- **User Story 1 (Phase 3)**: depends on Foundational only
- **User Story 2 (Phase 4)**: depends on Foundational only. It does **not** depend on US1 — pruning is
  driven by set difference, so it is demonstrable with a deleted file and needs no ignore rules
- **User Story 3 (Phase 5)**: depends on Foundational only. Independent of US1 and US2; with neither
  present it previews the include/dot-path resolution and reports `would_remove` from the existing
  document set
- **Polish (Phase 6)**: depends on every story that is being shipped

### Within Each User Story

- Tests are written first and must fail before implementation (repo TDD convention)
- `kgmd/ignore.py` before its `kgmd/ingest.py` wiring; `kgmd/ingest.py` before its `kgmd/cli.py`
  rendering
- Documentation tasks last within the story, but **inside** the story — not deferred to Polish, or
  the story's checkpoint leaves a red suite

### Sequential by shared file (never `[P]` together)

| File | Tasks |
|---|---|
| `kgmd/ingest.py` | T003, T004, T011, T024, T025, T026, T027, T036 |
| `kgmd/ignore.py` | T009, T010, T012 |
| `kgmd/cli.py` | T013, T028, T037, T038 |
| `tests/test_ingest.py` | T002, T008, T014, T019, T020, T021, T022, T023, T034 |
| `tests/test_ignore.py` | T006, T007 |
| `docs/reference/cli.md` | T018, T039, T040, T041 |
| `docs/reference/configuration.md` | T015, T016 |
| `docs/guides/maintenance.md` | T017, T029, T030 |

### Parallel Opportunities

- T006, T007, T008 — three test files at the start of US1 (`test_ignore.py` twice is sequential; T008
  is a different file, so T006+T008 or T007+T008 pair)
- T015, T016, T017, T018 — four documentation files in US1, all independent
- T029, T030, T031, T032, T033 — five documentation files in US2, all independent
- T034 and T035 — different test files in US3
- T042 and T043 — different documentation files in Polish
- With multiple developers, all three stories can run concurrently once Phase 2 is done; the shared
  files above are the only contention points

---

## Parallel Example: User Story 2 documentation

```bash
# Five independent files, one agent each:
Task: "Correct the deleted/renamed rows in docs/guides/maintenance.md"
Task: "Update the orphan-entity statements in docs/guides/maintenance.md"   # same file — NOT parallel
Task: "Remove the stale limitation from docs/examples/personal-notes.md"
Task: "Fix the deleted-notes claim in docs/examples/mcp-assistant.md"
Task: "Add the guard entry to docs/guides/troubleshooting.md"
```

The two `maintenance.md` tasks (T029, T030) must run in sequence; the other three are genuinely
parallel.

## Parallel Example: User Story 1 tests

```bash
Task: "Parsing tests in tests/test_ignore.py"                # T006
Task: "Ignore-integration cases in tests/test_ingest.py"     # T008 — different file, parallel
# T007 extends tests/test_ignore.py, so it follows T006
```

---

## Implementation Strategy

### MVP First (Foundational + User Story 1)

1. Phase 1 — baseline recorded
2. Phase 2 — `scan_corpus_files` in place, proven to change nothing
3. Phase 3 — `.kgmdignore` excludes paths, with docs
4. **STOP and VALIDATE**: quickstart Scenarios 1 and 3; `make test` green

This is a coherent, shippable increment: exclusion works for any corpus built after the ignore file
exists. Its honest limitation is that an already-indexed file that becomes ignored stays in the graph
— which is exactly what US2 fixes, and why US2 is not optional for a corpus that already has a graph.

### Incremental Delivery

1. Foundational → nothing observable changes
2. + US1 → exclusion works (MVP)
3. + US2 → the graph shrinks with the file set; deleted and renamed notes stop lingering
4. + US3 → rules become inspectable before spending
5. Polish → contributor docs, README orientation, full gate

### Recommended full-feature order

US1 → US2 → US3. US2 carries the correctness risk (stale vectors, dangling relations, the
destructive-pattern guard), so it should land while the design reasoning is fresh rather than after
the lower-risk preview work.

---

## Notes

- `[P]` means different files and no dependency on an incomplete task
- Every user-story task carries its story label for traceability
- Verify tests fail before implementing
- Commit after each task or logical group, with a capitalized imperative subject describing the why
- Never use `--no-verify`; never skip or delete a failing test in place of fixing it
- Do not fix `kgmd reset`'s missing vector cleanup or its `VACUUM`-in-transaction defect here — both
  are pre-existing, documented, and out of scope for this feature
