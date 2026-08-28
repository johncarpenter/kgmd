# Phase 1 Validation Guide: Project Documentation Set

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-28

How to prove this feature works. This is a validation/run guide — implementation belongs in
`tasks.md`. Content contracts live in [contracts/page-conventions.md](./contracts/page-conventions.md)
and [contracts/documented-surface.md](./contracts/documented-surface.md); entity rules in
[data-model.md](./data-model.md).

> Do not confuse this file with the deliverable `docs/quickstart.md`, which is a *user* onboarding
> page. This file validates the feature; that file is part of the feature.

## Prerequisites

```bash
cd /Users/john/Documents/Workspace/2Lines/kgmd
make install          # pip install -e ".[dev]"
```

No provider credential is required for any automated check (Constitution Principle V, FR-044).

## A. Automated validation — runs in the blocking gate

```bash
# The documentation checks alone
python -m pytest tests/test_docs.py -v

# The full gate, exactly as CI runs it
ruff check .
python -m pytest -v
```

**Expected**: all documentation tests pass, and the pre-existing suite (9 modules, ~50 tests) is
unaffected. Runtime added by the documentation module should be under 1 second.

Mapping of assertions to requirements is tabulated in
[contracts/documented-surface.md](./contracts/documented-surface.md#contract-tests-bidirectional-offline)
and [contracts/page-conventions.md](./contracts/page-conventions.md#enforcement-summary).

## B. Prove the gate actually gates (negative validation)

A coverage test that never fails is decoration. Each scenario below MUST produce a **failing** test,
then be reverted. This is the single most important validation in this guide — it is what would have
caught the README's six phantom MCP tool names.

| # | Temporary change | Expected failure |
|---|---|---|
| B-1 | Add a throwaway `@main.command()` named `zzz` to `kgmd/cli.py` | `test_all_commands_documented` — undocumented command |
| B-2 | Delete the `### reset` section from `docs/reference/cli.md` | `test_all_commands_documented` — undocumented command |
| B-3 | Add a `### get_entity` heading to `docs/guides/mcp.md` | `test_all_mcp_tools_documented` / `test_no_phantom_entries` — documents a tool that does not exist |
| B-4 | Add `llm.top_p: 0.9` to `DEFAULT_CONFIG` | `test_all_config_keys_documented` — undocumented key |
| B-5 | Add an option `--verbose` to `kgmd stats` | `test_all_parameters_documented` — undocumented parameter |
| B-6 | Change `kgmd/__init__.py` to `__version__ = "0.2.0"` | `test_version_stamps` — all 15 stamps stale |
| B-7 | Reword `Database not found:` in `kgmd/cli.py` | `test_quoted_errors_exist_in_source` — troubleshooting quotes a message no longer emitted |
| B-8 | Rename `docs/reference/export.md` | `test_internal_links_resolve` — dangling links from the index |
| B-9 | Paste `sk-abcdefghij0123456789abcdef` into a walkthrough | `test_no_credential_shaped_strings` |
| B-10 | Move a page to `docs/a/b/c.md` | `test_two_link_reachability` |

```bash
# after each temporary change
python -m pytest tests/test_docs.py -x -q     # expect exactly the named failure
git checkout -- .                             # revert before the next scenario
```

**Acceptance**: 10 of 10 scenarios fail as predicted. Any scenario that passes means that check is
not wired up.

## C. Per-story validation

### US1 — Zero to queryable graph (P1)

```bash
# Read only these two pages, in order, on a machine with no kgmd installed:
#   docs/install.md
#   docs/quickstart.md
```

**Pass when**: a reader with no prior exposure reaches a built graph and one successful query in
under 15 minutes of active work (SC-001), consulting no source code, no database, and no search
engine (SC-003). Two paths MUST both work: the fixtures path (git checkout) and the inline
mini-corpus heredoc path (`pip install` only, R-005).

**Timed**: record actual elapsed minutes; SC-001 is a number, not a vibe.

### US2 — Reference lookup (P2)

```bash
# Spot-check the inventory by hand against the live tool
kgmd --help
kgmd neighbors --help
```

**Pass when**: `--help` output for every command is fully represented in `docs/reference/cli.md`
(automated by A), all 19 config keys are present with defaults and the 3 inert ones flagged, and
`docs/guides/mcp.md` lists the 7 registered names — `search`, `get_entity_tool`,
`list_entities_tool`, `get_neighbors_tool`, `find_path_tool`, `list_relations_tool`,
`get_schema_tool` (SC-002).

### US3 — Operate and maintain (P3)

Answerable from `docs/guides/maintenance.md` alone, with no trial and error (SC-010):

1. "I edited one note out of 200 — what will re-running redo?"
2. "How do I force a full re-extract?"
3. "What is the difference between `kgmd reset` and `kgmd reset --hard`?"
4. "I changed `embedding.model` and now it errors — what now?"
5. "Two builds at once — what happens, and how do I clear a stale lock?"
6. "Where is the run log, and does it contain my note contents?" (answer MUST be: metadata only)

### US4 — Use cases (P4)

```bash
# Requires a credential; NOT part of the automated gate
export OPENROUTER_API_KEY="sk-..."
cd $(mktemp -d) && mkdir notes && cp <repo>/tests/fixtures/*.md notes/
cd notes && kgmd init && kgmd build
```

Then follow each of the three walkthroughs end to end. **Pass when** all three complete as written
against the fixture corpus (SC-007) and each states goal, prerequisites, input, commands, expected
output, and limitations (FR-033).

### US5 — Contributor onboarding (P5)

```bash
# Using only docs/contributing/development.md, from a fresh clone:
make install && make lint && make test
```

**Pass when**: a first-time contributor reaches a clean run in under 10 minutes (SC-009), and can
state from `docs/contributing/architecture.md` where a new pipeline stage's code, prompt, tests, and
documentation each belong.

## D. Manual pre-release verification (the residue)

Deterministic checks cannot execute provider-calling examples (R-006). Before each release, run and
tick:

- [ ] Every `bash` block in `docs/quickstart.md` executed verbatim against a fresh corpus.
- [ ] All three walkthroughs in `docs/examples/` executed end to end against `tests/fixtures/`.
- [ ] `kgmd mcp` connected from a real assistant client using the documented config block, and at
      least one tool call round-tripped.
- [ ] Windows global-config path confirmed on an actual Windows machine
      (`%LOCALAPPDATA%\kgmd\kgmd\config.yaml`) — derived from source, never executed (R-010).
- [ ] Install path confirmed from PyPI (`pip install kgmd`) in a clean virtualenv, including the
      loadable-extension caveat.
- [ ] Version stamps updated with the version bump (B-6 makes this blocking anyway).

This checklist is itself a deliverable: it lives in `docs/contributing/release.md`.

## E. Exit criteria

| Criterion | Verified by | Automated? |
|---|---|---|
| SC-001 15-minute onboarding | C/US1, timed | no |
| SC-002 100% surface coverage | A | **yes** |
| SC-003 no source-reading required | C/US1 | no |
| SC-004 examples run as written | D | no (by design) |
| SC-005 top failure modes covered | A (quoted errors exist) + C/US3 | partial |
| SC-006 two-link reachability | A | **yes** |
| SC-007 three walkthroughs reproducible | C/US4 | no |
| SC-008 zero known mismatches at release | A + B + D | partial |
| SC-009 10-minute contributor setup | C/US5, timed | no |
| SC-010 maintenance questions answerable | C/US3 | no |
| SC-011 no credentials in the gate | A (`pytest` passes with no keys set) | **yes** |

## F. Definition of done

- [ ] 15 pages exist at the paths fixed in [plan.md](./plan.md#source-code-repository-root).
- [ ] `tests/test_docs.py` passes; `ruff check .` clean; full `pytest -v` green on the local
      interpreter (CI covers 3.10–3.13).
- [ ] All 10 negative scenarios in section B fail as predicted, then revert clean.
- [ ] `README.md` trimmed to orientation, MCP tool names corrected, links into `docs/` present.
- [ ] Constitution amended to v1.1.0 naming both documentation surfaces (plan.md Complexity
      Tracking) — MUST land before or with implementation.
- [ ] `docs/contributing/release.md` contains the section D checklist.
