# Implementation Plan: Project Documentation Set

**Branch**: `001-project-documentation` | **Date**: 2026-08-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-project-documentation/spec.md`

## Summary

Create a `docs/` folder holding 15 markdown pages that cover install, quickstart, concepts, full
reference (CLI, configuration, export), operations/maintenance, troubleshooting, three end-to-end
use-case walkthroughs, and contributor/maintainer guidance. `README.md` is reduced to orientation
plus links.

The technical core of this feature is not prose — it is **making documentation drift detectable**.
The tool's own surface is introspectable at runtime (Click command tree, `DEFAULT_CONFIG`, the
FastMCP tool registry, the `--format` choice list), so a single offline pytest module
(`tests/test_docs.py`) can assert bidirectional coverage between the real surface and the reference
pages, verify internal link integrity, verify per-page version stamps, and verify that quoted error
strings in the troubleshooting page still exist in the source. No new dependencies, no network, no
credentials.

Baseline measured during Phase 0 (see [research.md](./research.md)): the current `README.md`
documents 12 of 16 commands, ~17 of 19 configuration keys, and — critically — **6 of its 7 MCP tool
names are wrong** (it lists `get_entity`; the server registers `get_entity_tool`). Any user who
followed the README to script against the MCP surface would get tool-not-found errors. This is the
concrete cost of having no verified documentation, and it is what the coverage test prevents from
recurring.

## Technical Context

**Language/Version**: CommonMark markdown for content; Python 3.10+ (package floor) for the
verification module

**Primary Dependencies**: none added. Verification uses `pytest` (already a dev dependency) plus
stdlib `ast`, `re`, `pathlib`; surface inventory comes from the already-installed `click` and `mcp`
packages via the project's own modules

**Storage**: N/A — documentation is plain files versioned in the repository; no application state is
touched by this feature

**Testing**: `pytest`, one new module `tests/test_docs.py`, fully offline (no provider calls, no
model downloads, no credentials), consistent with Constitution Principle V

**Target Platform**: repository-hosted markdown rendered by GitHub; readers on macOS, Linux, and
Windows (configuration paths documented per platform)

**Project Type**: CLI tool + library — in-repo documentation set, no site generator

**Performance Goals**: the documentation checks add < 1 s to the existing suite; any topic reachable
within 2 links from the index

**Constraints**: no new runtime or dev dependencies; no network access or credentials in automated
checks; `ruff` line-length 100 applies to the new test module; documentation is not published as a
rendered site in this feature; no application source behaviour changes

**Scale/Scope**: 15 pages; verified surface = 16 commands, 1 global option, 49 command
parameters (9 positional arguments + 40 options), 19 configuration keys, 7 MCP tools, 3 export
formats; 3 walkthroughs; ≥ 7 troubleshooting entries

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` v1.0.0.

| Principle | Applies? | Assessment |
|---|---|---|
| **I. Single Durable Artifact, Versioned Schema** | Indirectly | PASS. No code touches storage. Docs must describe `.kgmd/graph.db` as the single reset unit and must state the `user_version`/embedding-model immutability rules rather than inventing an in-place migration story (FR-022, FR-026). |
| **II. Deterministic, Mockable LLM Boundary** | Indirectly | PASS. No new LLM call sites. Docs must state that prompts are overridable from `.kgmd/prompts/` and that the run log holds metadata only (FR-027). Automated checks make zero provider calls. |
| **III. Dual-Surface Parity Over One Query Layer** | Yes | PASS, and enforced. The coverage test asserts the MCP surface is documented as completely as the CLI surface (FR-018, FR-041). This is what caught the wrong tool names. |
| **IV. Content-Hash Incrementality** | Indirectly | PASS. Docs must describe hash-based skipping and `--force`, and must not claim mtime-based behaviour (FR-023). |
| **V. Offline-Deterministic Test Gate** | Yes | PASS. `tests/test_docs.py` uses stdlib + already-installed packages, reads only repo files, no `tmp_path` mutation of user state, no network, no sleeps, no randomness. Live provider examples are verified manually pre-release, never in CI (FR-043, FR-044, SC-011). |
| **Tech constraints: flat package, no new deps** | Yes | PASS. Nothing added under `kgmd/`; one new file under `tests/`. Zero dependency additions. |
| **Tech constraints: config keys must be consumed** | Yes | PASS with disclosure. Constitution records three accepted-but-inert keys as debt; FR-017 requires docs to mark them inert rather than implying they work. Docs disclose, they do not fix. |
| **Workflow: canonical Make targets / CI gate** | Yes | PASS. Checks run inside the existing `make test` / `pytest -v` gate; no new tooling, no new CI job. |
| **Governance: "documentation as contract"** | **Conflict** | **REQUIRES AMENDMENT.** The constitution names `README.md` as *the* user-facing specification. This feature makes `docs/` authoritative for depth (FR-003). See Complexity Tracking; a v1.1.0 amendment must land before or with implementation. |

**Gate result**: PASS with one recorded governance amendment dependency. No principle is violated;
one governance sentence becomes stale and must be amended rather than silently contradicted.

### Post-design re-check (after Phase 1)

Re-evaluated after `research.md`, `data-model.md`, `contracts/`, and `quickstart.md` were produced.
Design decisions that could have introduced violations, and their outcome:

| Design decision | Risk it created | Outcome |
|---|---|---|
| Coverage test enumerates MCP tools via `ast` instead of importing `kgmd.mcp_server` | Importing that module reaches `fastembed`, which could download a model during tests → Principle V violation | **AVOIDED.** `ast`-based enumeration keeps the test synchronous, import-free, and offline (research R-003). |
| Verification placed in `tests/test_docs.py` | A new `scripts/` entry point or CI job would create a second enforcement convention | **PASS.** Runs inside the existing `pytest -v` gate; no new Make target, no new workflow, no pre-commit. |
| Zero new dependencies for markdown parsing | A markdown/link-checking library would breach "adding a dependency REQUIRES justification" | **PASS.** Plain `re` over lines is sufficient because page conventions (contracts/page-conventions.md) are machine-parseable by construction. |
| Sample corpus reuses `tests/fixtures/` rather than copying notes into `docs/` | A second corpus would drift from the exact counts existing tests pin | **PASS.** Single corpus; the `pip`-only reader is served by an inline heredoc whose documented output is shape-only, so no nondeterministic count is ever asserted in prose (research R-005). |
| Documenting the real `_tool`-suffixed MCP names | Tempting to "fix" the names while writing the page → scope creep and a breaking change to a public surface | **PASS, recorded.** Docs describe reality; rename deferred to its own spec (Complexity Tracking row 2). |
| Version stamp on all 15 pages | A version bump now fails the suite until stamps are updated — friction in the release path | **ACCEPTED, intentional.** This is the forcing function FR-004 asks for; `docs/contributing/release.md` lists stamp updates as a release step. |
| Manual pre-release execution of provider-calling examples | Could have been automated in CI with real credentials | **PASS.** Automating it would violate Principle V and FR-044; the residue is an explicit checklist in `docs/contributing/release.md`, validated by quickstart.md section D. |

**Post-design gate result**: PASS. No new violations introduced. The single pre-existing item — the
governance amendment for `docs/` authority — remains the only entry in Complexity Tracking and is a
hard dependency for implementation, not a waiver.

## Project Structure

### Documentation (this feature)

```text
specs/001-project-documentation/
├── plan.md              # This file (/speckit.plan command output)
├── spec.md              # Feature specification
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── documented-surface.md
│   └── page-conventions.md
├── checklists/
│   └── requirements.md  # Spec quality checklist (/speckit.specify output)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
docs/                              # NEW - the deliverable documentation set
├── README.md                      # Entry index, grouped by reader intent (FR-002)
├── install.md                     # Install methods, interpreter caveat, credentials (FR-005..FR-008)
├── quickstart.md                  # Zero to queryable graph (FR-009..FR-011)
├── concepts.md                    # Pipeline stages + vocabulary + single-file state (FR-020..FR-022)
├── guides/
│   ├── mcp.md                     # All 7 tools + client config per platform (FR-018)
│   ├── maintenance.md             # Incrementality, reset, lock, cost, backup (FR-023..FR-029)
│   └── troubleshooting.md         # Symptom -> cause -> fix, quoted errors (FR-030, FR-031)
├── reference/
│   ├── cli.md                     # All 16 commands + global --debug (FR-012..FR-014)
│   ├── configuration.md           # All 19 keys + precedence + inert keys (FR-015..FR-017)
│   └── export.md                  # All 3 formats + consuming tools (FR-019)
├── examples/
│   ├── personal-notes.md          # Walkthrough 1 (FR-032)
│   ├── mcp-assistant.md           # Walkthrough 2 (FR-032)
│   └── graph-export.md            # Walkthrough 3 (FR-032)
└── contributing/
    ├── development.md             # Env setup + local check sequence (FR-036)
    ├── architecture.md            # Layering, one-way deps, shared query layer (FR-037, FR-038)
    └── release.md                 # Version bump, publish trigger, prohibitions (FR-039)

tests/
└── test_docs.py                   # NEW - offline coverage/link/stamp/error-string checks (FR-041..FR-044)

README.md                          # MODIFIED - trimmed to orientation; fixes the wrong MCP tool
                                   #   names; links into docs/ (FR-003)
.specify/memory/constitution.md    # MODIFIED (amendment) - extend doc-as-contract to docs/
```

**Structure Decision**: Single flat `docs/` tree with four intent subdirectories
(`guides/`, `reference/`, `examples/`, `contributing/`) plus four top-level entry pages
(`README.md`, `install.md`, `quickstart.md`, `concepts.md`). Grouping follows the reader-intent
groups the spec already mandates in FR-002, which map cleanly onto the Diátaxis split
(tutorial = quickstart, how-to = guides + examples, reference = reference, explanation = concepts).
Depth is capped at two levels so every page is reachable in ≤ 2 links from `docs/README.md`
(SC-006). No site generator, no `mkdocs.yml`, no generated API pages — those are explicitly out of
scope per the spec's Assumptions.

Verification lives in `tests/` rather than a new `scripts/` directory or a new CI job, because the
constitution makes `pytest -v` the single blocking gate; adding a parallel enforcement path would
create a second convention for no benefit.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Making `docs/` authoritative for depth while the constitution names `README.md` as *the* user-facing specification (Governance, "Documentation as contract") | The spec's core requirement is a documentation folder with extensive install/use/maintain coverage (FR-001, FR-003). A single README cannot hold 16 command entries, 19 configuration keys, 7 tool schemas, and 3 walkthroughs without becoming unnavigable. The obligation itself is unchanged — it now points at two surfaces. | Keeping everything in `README.md` was rejected: it fails FR-001 outright and fails SC-006 (two-link reachability) since a single file has no navigation. Leaving the constitution stale was rejected: it would leave the Constitution Check gate contradicting a shipped feature, which the governance section explicitly forbids ("Undocumented violations MUST be reverted"). Resolution is a v1.1.0 amendment naming both surfaces, tracked as an implementation dependency, not a waiver. |
| Documenting the MCP tool names as `get_entity_tool`, `list_entities_tool`, `get_neighbors_tool`, `find_path_tool`, `list_relations_tool`, `get_schema_tool` — names that read as implementation artefacts | These are the names the server actually registers (verified by calling `mcp.list_tools()`; see research.md R-002). Documentation must describe reality, and a docs-scoped feature must not change runtime behaviour. | Renaming the tools to the clean names the README already advertises was rejected **for this feature only**: it is a breaking change to the integration surface for anyone whose client config or prompt references the current names, so it needs its own spec, a compatibility decision, and its own tests. Recorded as a follow-up in research.md R-002 with a recommendation to run `/speckit.specify` for it. |
