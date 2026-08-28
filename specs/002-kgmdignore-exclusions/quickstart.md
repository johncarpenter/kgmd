# Quickstart: validating `.kgmdignore`

**Feature**: [spec.md](./spec.md) | **Contracts**: [contracts/](./contracts/)

Runnable checks that prove the feature works end to end. Every scenario is offline — no provider
credential, no model download — except Scenario 5, which is explicitly marked as the only one that
spends money and is optional.

## Prerequisites

```bash
make install          # pip install -e ".[dev]"
```

No `OPENROUTER_API_KEY` is needed for Scenarios 1–4 and 6: ingest, discovery, and pruning never
reach the language-model boundary.

## Scenario 1 — Exclusion works (FR-001 … FR-005)

```bash
mkdir -p /tmp/kgmd-demo/{notes,archive,drafts}
cd /tmp/kgmd-demo
printf '# Today\n\nSarah Chen leads Atlas.\n' > notes/today.md
printf '# Old\n\nSuperseded.\n'               > archive/old.md
printf '# Decisions\n\nKeep this one.\n'      > archive/2024-decisions.md
printf '# Draft\n\nHalf an idea.\n'           > drafts/idea.md
printf '# Changelog\n\n- thing\n'             > notes/CHANGELOG.md

kgmd init
cat >> .kgmdignore <<'EOF'
archive/
drafts/
**/CHANGELOG.md
!archive/2024-decisions.md
EOF

kgmd build --dry-run
```

**Expected**: `notes/today.md` and `archive/2024-decisions.md` are listed; `archive/old.md`,
`drafts/idea.md`, and `notes/CHANGELOG.md` are counted as ignored. The negation re-admitting a file
inside an excluded directory is the deliberate divergence from git — see
[contracts/kgmdignore-format.md](./contracts/kgmdignore-format.md).

## Scenario 2 — The preview is machine-readable and writes nothing (FR-017, FR-018)

```bash
rm -f .kgmd/graph.db          # prove a dry run does not create it
kgmd build --dry-run --json | python -m json.tool
test -f .kgmd/graph.db && echo "FAIL: dry run created the database" || echo "OK: no database created"
kgmd build --json ; echo "exit=$?"
```

**Expected**: a single JSON object matching the shape in
[contracts/cli-build-dry-run.md](./contracts/cli-build-dry-run.md), with `counts.would_remove` of
`0`; no `graph.db`; and `kgmd build --json` alone failing with `--json requires --dry-run.` and
`exit=1`.

## Scenario 3 — Absent `.kgmdignore` changes nothing (FR-009)

```bash
mv .kgmdignore /tmp/kgmd-demo-ignore-backup
kgmd build --dry-run --json | python -c 'import json,sys; d=json.load(sys.stdin); print(d["counts"])'
mv /tmp/kgmd-demo-ignore-backup .kgmdignore
```

**Expected**: `ignored` is `0` and `included` is every `.md` file in the tree. This is the regression
guard for SC-003 — the same assertion exists as a test over `tests/fixtures/`.

## Scenario 4 — A newly excluded note leaves an existing graph (FR-011 … FR-016)

The offline version of this is the authoritative check, because it needs no provider:

```bash
python -m pytest tests/test_ingest.py -v -k "prune or ignored"
```

**Expected**: passing assertions that after adding an ignore rule covering an already-indexed
document and re-running ingest, the `documents` row, its `chunks`, its `entity_mentions`, its
evidence-bound `relations`, its `vec_chunks` / `vec_entity_mentions` rows, and any entity left with
no mention and no relation are all gone — while untouched documents and their derived rows are
unchanged. Ordering and cascade reasoning is in [data-model.md](./data-model.md) §3.

The stale-vector case is the one to read first: it asserts the `vec_chunks` row for a removed chunk
is deleted, because `chunks.id` values are reused and `embed_new_chunks` skips any chunk that already
has a vector row.

## Scenario 5 — End-to-end with a real provider (optional, costs money)

```bash
cd /tmp/kgmd-demo
export OPENROUTER_API_KEY=...      # not read, stored, or logged by kgmd
kgmd build                         # indexes 2 files, not 5
kgmd find "Atlas"                  # hits notes/today.md
kgmd stats

printf 'archive/2024-decisions.md\n' >> .kgmdignore
kgmd build                         # reports 1 document removed
kgmd find "Keep this one"           # no hit from the excluded note
```

**Expected**: the first build's summary reports 2 new documents; after the second build the ingest
line reports `Removed: 1`, and the excluded note no longer answers `kgmd find` (SC-005).

## Scenario 6 — Guard against emptying a graph (FR-015)

```bash
printf '*\n' >> .kgmdignore
kgmd build ; echo "exit=$?"
kgmd stats                          # unchanged
```

**Expected**: the build fails with a message saying the ignore rules exclude every file while the
graph still holds documents, exit 1, and `kgmd stats` shows the graph untouched. `kgmd build
--dry-run` in the same state exits 0 and simply reports zero included files — a dry run is a read,
so the guard does not apply.

## Cleanup

```bash
rm -rf /tmp/kgmd-demo
```

## Full gate before proposing the change

```bash
make format && make lint && make test
```

`make test` includes `tests/test_docs.py`, which fails if any new user-facing surface is
undocumented or if a documented surface names something that does not exist — in both directions. The
documentation edits listed in [research.md](./research.md) §R11 are part of this change, not a
follow-up.
