---

description: "Task list for the Project Documentation Set feature"
---

# Tasks: Project Documentation Set

**Input**: Design documents from `/specs/001-project-documentation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Verification tasks here are **not optional TDD scaffolding** — FR-041 through FR-044
make the automated documentation checks a *deliverable* of this feature. `tests/test_docs.py` is
feature code, not test-first ceremony. Within each story the check is added **after** its pages, so
the suite never sits red between tasks.

**Organization**: Tasks are grouped by user story. Each story delivers usable documentation on its
own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Include exact file paths in descriptions

## Path Conventions

Repository root is `/Users/john/Documents/Workspace/2Lines/kgmd`. Deliverables land in `docs/`
(15 pages), `tests/test_docs.py` (1 new module), `README.md` (modified), and
`.specify/memory/constitution.md` (amendment). No file under `kgmd/` is modified by this feature —
it is documentation-only, per the plan's Structure Decision.

## Critical serialization notice

Two files are touched by every story and therefore **cannot** be parallelized across stories:

- `tests/test_docs.py` — each story appends its own check functions.
- `docs/README.md` — each story adds its index links.

Page authoring (different files) parallelizes freely. Each story's index-link and check tasks are
deliberately the last two tasks of its phase so the file is touched once per story.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Directory scaffolding and the governance prerequisite

- [X] T001 Create the documentation directory tree `docs/`, `docs/guides/`, `docs/reference/`, `docs/examples/`, `docs/contributing/` (directories only — C-9 forbids placeholder or "coming soon" files)
- [X] T002 [P] Amend `.specify/memory/constitution.md` to v1.1.0 so the "Documentation as contract" governance rule names both `README.md` (orientation) and `docs/` (depth), per plan.md Complexity Tracking row 1; update the Sync Impact Report comment and the `Last Amended` date
- [X] T003 [P] Create `docs/README.md` as the entry index: H1, version stamp line `> Applies to kgmd 0.1.x`, audience paragraph, and the five intent-group headings (`## Get started`, `## Understand`, `## Reference`, `## Operate`, `## Examples`, `## Contribute`) with no links yet — links are added by each story

**Checkpoint**: Tree exists, governance no longer conflicts with the feature, index shell is stamped.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The verification harness every later story extends

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. All four tasks touch
`tests/test_docs.py`, so they are strictly sequential.

**Design constraint**: every check in this phase MUST iterate over *discovered* files
(`docs/**/*.md`), never over a hard-coded list of the 15 planned pages. A fixed inventory assertion
would sit red for the entire implementation; it is added once at the end (T045).

- [X] T004 Create `tests/test_docs.py` with shared helpers, stdlib-only plus already-installed packages: `docs_pages()` discovery, `read_page()` returning (title, stamp, body), `internal_links()` extraction, `package_source_text()` concatenating `kgmd/**/*.py`, and the six introspection helpers from contracts/documented-surface.md (`click_commands()`, `click_params()`, `global_options()`, `config_keys()` flattening `DEFAULT_CONFIG` to dotted paths, `mcp_tool_names()` via `ast` over `kgmd/mcp_server.py`, `export_formats()`); no `fastembed` or `litellm` import, no network, no `asyncio` (research R-003)
- [X] T005 Add `test_page_skeleton` and `test_version_stamps` to `tests/test_docs.py` enforcing convention C-1: single H1 on line 1, stamp on line 2 matching `^> Applies to kgmd (\d+)\.(\d+)\.x$`, and major/minor equal to `kgmd.__version__`
- [X] T006 Add `test_internal_links_resolve` and `test_two_link_reachability` to `tests/test_docs.py` per convention C-7: relative internal targets resolve on disk, external URLs never fetched, every discovered page reachable from `docs/README.md` within two links (BFS over the link graph)
- [X] T007 Add `test_no_credential_shaped_strings` and `test_no_absolute_paths` to `tests/test_docs.py` per convention C-9: reject `sk-` followed by 20+ characters, reject `/Users/` and `C:\Users\` outside fenced example placeholders

**Checkpoint**: `python -m pytest tests/test_docs.py -v` green with only the index present. Harness ready; stories may begin.

---

## Phase 3: User Story 1 - Get from zero to a queryable graph (Priority: P1) 🎯 MVP

**Goal**: A reader with nothing installed reaches a built graph and one successful query using only
two pages.

**Independent Test**: On a clean machine, follow `docs/install.md` then `docs/quickstart.md` and
reach a query result in under 15 minutes with no source-code reading (SC-001, SC-003).

**Phase constraint**: US1 pages MUST NOT link to `docs/concepts.md` or any `docs/reference/` page —
those files do not exist yet and T006's link check would fail. Forward links are added in T026.

- [X] T008 [P] [US1] Write `docs/install.md` covering install methods (`pip install kgmd`, `uv tool install kgmd`), supported interpreters 3.10–3.13, a post-install verification step, the loadable-SQLite-extension prerequisite with the exact failure symptom and the `pyenv` remedy, required provider credential as an environment variable, the explicit statement that credentials are never stored/prompted/logged, and which capabilities need no credential because embeddings run locally via fastembed (FR-005–FR-008)
- [X] T009 [P] [US1] Write `docs/quickstart.md`: ordered `kgmd init` → export credential → `kgmd build` → `kgmd find`/`kgmd entities` sequence with expected output per step, a provider-cost notice before the first `build`, and two corpus paths — the `tests/fixtures/` path for readers with a git checkout, and a self-contained two-note heredoc for `pip install`-only readers whose expected output is described by shape not counts (FR-009–FR-011, research R-005)
- [X] T010 [US1] Add `test_fixture_references_exist` to `tests/test_docs.py`: every `tests/fixtures/*.md` filename referenced by any page resolves on disk
- [X] T011 [US1] Add "Get started" links for `install.md` and `quickstart.md` to `docs/README.md`
- [X] T012 [US1] Trim `README.md` to orientation: keep overview, feature bullets, install, and a ~10-line shortest-path snippet; add a link table pointing into `docs/`; leave the MCP tool table alone for now (T027 replaces it) (FR-003, research R-009)
- [ ] T013 [US1] Verify US1: run `python -m pytest tests/test_docs.py -v`, then walk both pages end to end on a clean virtualenv (fixtures path and heredoc path) and record actual elapsed minutes against SC-001  <!-- PARTIAL: automated portion done (checks green, both corpus paths reviewed); human clean-machine timing pending -->

**Checkpoint**: Onboarding is complete and self-contained. Shippable as MVP even with no other page written.

---

## Phase 4: User Story 2 - Look up any command, option, or setting (Priority: P2)

**Goal**: Complete, machine-verified reference for every user-visible surface — closing the 4
undocumented commands, 2 undocumented config keys, and 6 wrong MCP tool names measured in
research.md.

**Independent Test**: Every identifier in
[contracts/documented-surface.md](./contracts/documented-surface.md) appears in the reference with
purpose, default, and example; `kgmd --help` and `kgmd <cmd> --help` are fully represented (SC-002).

- [X] T014 [P] [US2] Write `docs/reference/cli.md`: one `### <command>` section for all 16 commands (`init`, `stats`, `build`, `extract`, `resolve`, `induce`, `find`, `entities`, `relations`, `entity`, `neighbors`, `path`, `schema`, `export`, `reset`, `mcp`) per convention C-2, with a parameter table covering all 49 parameters, at least one `bash` example each, a `**Structured output**:` block for the 8 `--json` commands, and the global `--debug` option documented once (FR-012–FR-014)
- [X] T015 [P] [US2] Write `docs/reference/configuration.md`: table row per convention C-3 for all 19 dotted keys with default, accepted values, and effect; the three-layer precedence rule with a worked merge example; the per-platform global config paths from research R-010 including the doubled `%LOCALAPPDATA%\kgmd\kgmd\config.yaml`; the literal marker `Accepted but currently has no effect` on `extraction.max_entities_per_chunk`, `extraction.max_relations_per_chunk`, `induction.include_attribute_summary`; and the `llm.max_tokens` divergence note (FR-015–FR-017, research R-011)
- [X] T016 [P] [US2] Write `docs/reference/export.md`: all three `--format` values (`jsonld`, `cypher`, `graphml`), what each file contains, the consuming external tool, and both stdout and `--output/-o` usage (FR-019)
- [X] T017 [P] [US2] Write `docs/guides/mcp.md`: one `### <registered_name>` section for the 7 real tool names (`search`, `get_entity_tool`, `list_entities_tool`, `get_neighbors_tool`, `find_path_tool`, `list_relations_tool`, `get_schema_tool`) with parameters and returns per convention C-4, a note explaining the `_tool` suffix for readers who saw the old README table, a copy-pasteable client config block, per-platform client config file locations, and a prominent warning that the server resolves its database from the client's working directory (FR-018, research R-002)
- [X] T018 [P] [US2] Write `docs/concepts.md`: the three pipeline stages in order with what each reads and writes, the six vocabulary terms each under a `### <term>` heading (document, chunk, entity, mention, relation, induced schema), and the statement that all state lives in `.kgmd/graph.db` so deleting that file is a complete reset (FR-020–FR-022)
- [X] T019 [US2] Add `test_all_commands_documented`, `test_all_parameters_documented`, and `test_global_option_documented` to `tests/test_docs.py` asserting **set equality** between introspected Click surface and `### ` headings in `docs/reference/cli.md`
- [X] T020 [US2] Add `test_structured_output_parity` to `tests/test_docs.py`: the set of commands with an `as_json` parameter equals the set whose section contains a `**Structured output**:` block
- [X] T021 [US2] Add `test_all_config_keys_documented` and `test_inert_keys_marked` to `tests/test_docs.py`: flattened `DEFAULT_CONFIG` keys equal documented keys, and the three inert keys carry the literal marker
- [X] T022 [US2] Add `test_all_mcp_tools_documented` to `tests/test_docs.py` comparing `ast`-derived tool names against `### ` headings in `docs/guides/mcp.md` — this is the check that makes the 6-wrong-names class of defect impossible
- [X] T023 [US2] Add `test_all_export_formats_documented` to `tests/test_docs.py` comparing the `--format` `click.Choice` values against `docs/reference/export.md`
- [X] T024 [US2] Add `test_no_phantom_entries` to `tests/test_docs.py`: no documented command, parameter, config key, tool, or format identifier is absent from the code — the reverse direction that one-way coverage checks miss
- [X] T025 [US2] Add `test_concept_terms_defined` to `tests/test_docs.py`: all six vocabulary terms have a `### ` definition heading in `docs/concepts.md`
- [X] T026 [US2] Add "Understand" and "Reference" links to `docs/README.md` for `concepts.md`, `reference/cli.md`, `reference/configuration.md`, `reference/export.md`, `guides/mcp.md`; add forward links from `docs/quickstart.md` to `concepts.md` and `reference/cli.md` now that they exist
- [X] T027 [US2] Replace the incorrect MCP tool table in `README.md` (it names `get_entity`, `list_entities`, `get_neighbors`, `find_path`, `list_relations`, `get_schema` — 6 names that do not exist) with a pointer to `docs/guides/mcp.md`; also remove the configuration dump and export list now held in `docs/reference/`
- [X] T028 [US2] Verify US2: `python -m pytest tests/test_docs.py -v`, then spot-check `kgmd --help` and three `kgmd <cmd> --help` outputs against `docs/reference/cli.md` by hand

**Checkpoint**: US1 and US2 both work independently. Every user-visible surface is documented and drift is now mechanically blocked.

---

## Phase 5: User Story 3 - Operate and maintain a corpus over time (Priority: P3)

**Goal**: Answer "what will re-running cost and redo?" and "how do I get back to clean?" without
trial and error.

**Independent Test**: The six questions in [quickstart.md](./quickstart.md#us3--operate-and-maintain-p3)
are answerable from `docs/guides/maintenance.md` alone (SC-010).

- [X] T029 [P] [US3] Write `docs/guides/maintenance.md`: sha256 content-hash incrementality (what is skipped, what triggers reprocessing, what downstream state is invalidated, `--force`), the explicit statement that mtime is not authoritative, `kgmd reset` versus `kgmd reset --hard` with exactly what each removes and preserves, build-lock concurrency behaviour and stale-lock clearing, embedding-model immutability with the supported recovery path, the `.kgmd/logs/build.log` location with the metadata-only guarantee, provider-spend guidance naming which stages call the provider and which settings change call volume, and corpus backup/relocation (FR-023–FR-029)
- [X] T030 [P] [US3] Write `docs/guides/troubleshooting.md` with at least the seven required entries per convention C-5 (`**Symptom**:` line carrying the literal source-text prefix in an inline code span, then `**Cause**:` and `**Fix**:`): missing provider credential, interpreter without loadable-extension support, command run outside a corpus (`No .kgmd directory found`), database absent (`Database not found:`), embedding-model mismatch (`Database was initialized with embedding model`), build blocked by another build, unparseable provider response, and zero-entity build (FR-030, FR-031)
- [X] T031 [US3] Add `test_quoted_errors_exist_in_source` to `tests/test_docs.py`: every inline code span on a `**Symptom**:` line appears verbatim in `kgmd/**/*.py` (literal prefix up to the first interpolation, per research R-007)
- [X] T032 [US3] Add "Operate" links for `guides/maintenance.md` and `guides/troubleshooting.md` to `docs/README.md`
- [ ] T033 [US3] Verify US3: `python -m pytest tests/test_docs.py -v`, then answer all six US3 questions from the maintenance page alone and confirm each answer matches actual tool behaviour  <!-- PARTIAL: automated portion done; the six questions answered from the page by review, not by a fresh reader -->

**Checkpoint**: Operators can run the tool over months without guessing or over-resetting.

---

## Phase 6: User Story 4 - Decide whether the tool fits a real job (Priority: P4)

**Goal**: Three reproducible end-to-end walkthroughs an evaluator can run before committing time.

**Independent Test**: A reader picks one walkthrough and reaches the shown output using only it plus
`docs/install.md` (SC-007).

- [X] T034 [P] [US4] Write `docs/examples/personal-notes.md` — build a searchable graph over personal notes — using the convention C-6 section order (Goal, Prerequisites, Corpus, Steps, Expected output, Limitations), running against `tests/fixtures/` with a stated git-checkout prerequisite (FR-032–FR-034)
- [X] T035 [P] [US4] Write `docs/examples/mcp-assistant.md` — expose a corpus to an assistant client and ask questions through it — same section order, using the real `_tool`-suffixed names and calling out the working-directory requirement
- [X] T036 [P] [US4] Write `docs/examples/graph-export.md` — export into an external graph/visualization tool — same section order, showing what to do with the produced `graphml`/`cypher` file in Gephi or Neo4j
- [X] T037 [US4] Add `test_walkthrough_sections` to `tests/test_docs.py`: every `docs/examples/*.md` contains the six required C-6 section headings in order
- [X] T038 [US4] Add "Examples" links for the three walkthroughs to `docs/README.md`
- [ ] T039 [US4] Verify US4: `python -m pytest tests/test_docs.py -v`, then run all three walkthroughs end to end against `tests/fixtures/` with a real provider credential (manual — never in the gate, per FR-044)  <!-- PARTIAL: walkthrough structure verified; end-to-end runs need a provider credential -->

**Checkpoint**: Evaluators can self-serve. All reader-facing stories complete.

---

## Phase 7: User Story 5 - Contribute or maintain the codebase (Priority: P5)

**Goal**: A contributor sets up, passes the gate, and knows where new code, prompts, tests, and docs
belong.

**Independent Test**: From a fresh clone, using only `docs/contributing/development.md`, reach a
clean `make lint && make test` in under 10 minutes (SC-009).

- [X] T040 [P] [US5] Write `docs/contributing/development.md`: environment setup via `make install`, the canonical local check sequence `make format` → `make lint` → `make test`, the fact that CI runs `ruff check .` plus `pytest -v` across 3.10–3.13, and the rule that documentation ships in the same change as the capability it describes (FR-036, FR-040)
- [X] T041 [P] [US5] Write `docs/contributing/architecture.md`: module layering and the one-way dependency direction (`cli`/`mcp_server` → stages → `llm`/`embed`/`db` → `schema`), `query.py` as the single shared read layer behind both surfaces, where prompts (`kgmd/prompts/` overridable from `.kgmd/prompts/`), DDL (`kgmd/schema.py`), and tests live, and a link to `.specify/memory/constitution.md` as the governing document without restating its rules (FR-037, FR-038)
- [X] T042 [P] [US5] Write `docs/contributing/release.md`: version bump in `kgmd/__init__.py`, GitHub Release trigger, OIDC trusted publishing, the prohibition on manual `twine`/`--no-verify`, the requirement to update all 15 version stamps with the bump, and the manual pre-release verification checklist copied from [quickstart.md](./quickstart.md#d-manual-pre-release-verification-the-residue) including the Windows-path confirmation item (FR-039, research R-006, R-010)
- [X] T043 [US5] Add "Contribute" links for the three contributing pages to `docs/README.md`
- [ ] T044 [US5] Verify US5: `python -m pytest tests/test_docs.py -v`, then time a fresh-clone setup to a clean check run against SC-009  <!-- PARTIAL: automated portion done; fresh-clone timing needs a human -->

**Checkpoint**: All five stories independently functional. 15 pages present.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Lock the inventory, prove the gate actually gates, and close the release path

- [X] T045 Add `test_expected_pages_exist` to `tests/test_docs.py` asserting all 15 planned pages exist at the exact paths fixed in [plan.md](./plan.md#source-code-repository-root) — safe only now that every page is written (see Phase 2 design constraint)
- [X] T046 Run all 10 negative validation scenarios from [quickstart.md](./quickstart.md#b-prove-the-gate-actually-gates-negative-validation) (B-1…B-10) sequentially, reverting with `git checkout -- .` between each; confirm each produces exactly the predicted failure. **A scenario that passes means that check is not wired up and MUST be fixed.** Do not parallelize — every scenario mutates and reverts the working tree
- [X] T047 Run the full gate exactly as CI does per `.github/workflows/ci.yml`: `ruff check .` then `python -m pytest -v`; confirm the pre-existing 9 modules under `tests/` are unaffected and that `tests/test_docs.py` adds under 1 second
- [X] T048 Confirm `python -m pytest tests/ -v` passes with **no** provider credential set in the environment, proving `tests/test_docs.py` satisfies SC-011 and FR-044
- [X] T049 [P] Grep `docs/` for prohibited content per convention C-9: no `TODO`, no "coming soon", no unwritten sections, no restatement of constitutional rules in `docs/contributing/`
- [X] T050 [P] Final `README.md` review: verify it stands alone as the PyPI landing page (overview, install, shortest path, links) and that no incorrect MCP tool name survives anywhere in the file
- [ ] T051 Record the SC-001 and SC-009 timings measured in T013 and T044 into the release checklist in `docs/contributing/release.md` as the baseline to re-verify each release  <!-- PARTIAL: no baseline exists yet - recorded as such in docs/contributing/release.md -->
- [ ] T052 Confirm the Windows global-config path `%LOCALAPPDATA%\kgmd\kgmd\config.yaml` on an actual Windows machine, or mark it in `docs/reference/configuration.md` as derived-from-source and pending confirmation (research R-010 — it cannot be executed off-platform)  <!-- PARTIAL: cannot execute off-platform; Windows row now marked unconfirmed in the config reference -->

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. T002 (constitution amendment) is a hard prerequisite for merging, not for authoring.
- **Foundational (Phase 2)**: Depends on T001 and T003. **BLOCKS all user stories** — every story appends checks to the harness created in T004.
- **User Stories (Phases 3–7)**: All depend on Phase 2. Independent of each other for page authoring.
- **Polish (Phase 8)**: T045 depends on every page existing (all five stories). T046 depends on every check existing.

### User Story Dependencies

- **US1 (P1)**: After Phase 2. No story dependencies. Constrained not to link forward to unwritten pages.
- **US2 (P2)**: After Phase 2. Independent. T026 adds the forward links US1 deliberately omitted.
- **US3 (P3)**: After Phase 2. Independent — may link to `docs/reference/cli.md` only if US2 is already merged; otherwise defer those links to T032.
- **US4 (P4)**: After Phase 2. Content-wise benefits from US2's `guides/mcp.md` for T035; if run before US2, omit that cross-link.
- **US5 (P5)**: After Phase 2. Fully independent.

### Within Each User Story

- Pages first (parallel, different files) → check functions second (sequential, one shared file) → index links → verification.
- Checks come after pages so the suite is never left red between tasks.

### Parallel Opportunities

- **Setup**: T002 and T003 in parallel.
- **Foundational**: none — T004→T007 all touch `tests/test_docs.py`.
- **US1**: T008, T009 in parallel.
- **US2**: T014, T015, T016, T017, T018 all in parallel — the largest win in the feature (5 pages).
- **US3**: T029, T030 in parallel.
- **US4**: T034, T035, T036 in parallel.
- **US5**: T040, T041, T042 in parallel.
- **Polish**: T049, T050 in parallel. T046 MUST be alone.
- **Across stories**: page-authoring tasks from different stories can run concurrently; their check tasks and index-link tasks cannot, because `tests/test_docs.py` and `docs/README.md` are shared.

---

## Parallel Example: User Story 2

```bash
# Five reference pages, five different files, no interdependencies:
Task: "Write docs/reference/cli.md — 16 commands, 49 parameters, --debug, 8 structured-output blocks"
Task: "Write docs/reference/configuration.md — 19 keys, precedence, platform paths, 3 inert markers"
Task: "Write docs/reference/export.md — jsonld, cypher, graphml"
Task: "Write docs/guides/mcp.md — 7 registered _tool names, client config, cwd warning"
Task: "Write docs/concepts.md — 3 stages, 6 vocabulary terms, single-file state"

# Then, strictly sequential (all append to tests/test_docs.py):
#   T019 → T020 → T021 → T022 → T023 → T024 → T025
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup — tree, constitution amendment, index shell.
2. Phase 2: Foundational — the check harness (**blocks everything**).
3. Phase 3: US1 — `install.md` + `quickstart.md`.
4. **STOP and VALIDATE**: clean-machine walkthrough, timed against SC-001.
5. Shippable: onboarding is the adoption gate and delivers value with zero other pages written.

### Incremental Delivery

1. Setup + Foundational → harness green with only the index.
2. + US1 → new users can onboard (MVP).
3. + US2 → every surface documented; **the 6 wrong MCP tool names and 4 undocumented commands are fixed here** — highest defect-reduction increment.
4. + US3 → operators stop guessing about cost and reset.
5. + US4 → evaluators self-serve.
6. + US5 → contributors self-serve.
7. Polish → inventory locked, gate proven to gate.

If scope must be cut, cut from the bottom (US5, then US4). Never cut Phase 2 — without it the
documentation starts drifting on day one, which is the condition that produced the current defects.

### Parallel Team Strategy

1. Everyone waits on Phase 2 (it is one file; one person, four sequential tasks, short).
2. Then: Dev A → US1, Dev B → US2 (largest phase, 5 parallel pages), Dev C → US3, Dev D → US4+US5.
3. Serialize the check-function and index-link tasks through one owner, or coordinate directly —
   `tests/test_docs.py` and `docs/README.md` are the only contention points.

---

## Notes

- [P] = different files, no dependencies on incomplete tasks.
- 52 tasks total: 3 setup, 4 foundational, 6 US1, 15 US2, 5 US3, 6 US4, 5 US5, 8 polish.
- Constitution compliance is not a polish item — T002 clears the only recorded governance conflict before merge.
- Zero new dependencies. Zero changes under `kgmd/`. If a task seems to require either, stop: it is out of scope for this feature (see plan.md Complexity Tracking).
- The MCP tool rename is explicitly **not** in this feature. Document the real names; raise a separate spec.
- Commit after each task or logical group; every commit must leave `pytest -v` green.
- Stop at any checkpoint to validate a story independently.
