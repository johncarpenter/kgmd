# Phase 0 Research: Corpus Exclusions via `.kgmdignore`

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-28

Every decision below was verified against the code or a live probe, not assumed. Probe transcripts
are reproduced where the result decided the design.

---

## R1: Pattern matching without a new runtime dependency

**Decision**: Hand-roll a gitignore-subset pattern compiler in a new leaf module `kgmd/ignore.py`
that translates each pattern to a `re.Pattern` once at parse time. No new runtime dependency.

**Rationale**: Both stdlib candidates are provably wrong for this job.

`fnmatch` treats the path as an opaque string — its `*` crosses `/`:

```text
fnmatch.translate("*.md")            -> (?s:.*\.md)\Z      # `.*`, not `[^/]*`
fnmatch.fnmatch("a/b.md", "*.md")    -> True                # must be False for `/`-scoped globs
```

`PurePath.match` is right-anchored and its `**` is single-segment on the supported runtimes
(`full_match` arrived in 3.13; the floor is 3.10):

```text
PurePath("a/b.md").match("*.md")        -> True    # cannot express "only at root"
PurePath("a/b/d/c.md").match("a/**/c.md") -> False # `**` spans one segment only
PurePath("b.md").match("/b.md")         -> False   # leading-`/` anchoring unavailable
hasattr(PurePath, "full_match")         -> False   # on 3.12; absent on 3.10–3.12
```

So neither can express root anchoring, and neither can express recursive `**`. A translator is
~60 lines of `re.escape` plus four substitutions, and it is exactly the part that needs dense unit
tests anyway.

**Alternatives considered**:

- **`pathspec`** — gives real gitignore semantics for free. Rejected: the constitution requires
  justification for any new runtime dependency, `sqlite-vec` and `fastembed` already make installs
  fragile, and spec FR-022 plus the issue's acceptance criteria call for no new dependency. The
  semantics we need are a documented subset, not the full grammar.
- **`fnmatch` with a pre-split path** — matching segment lists instead of strings. Rejected: it
  collapses under `**`, which must match a variable number of segments, and the bookkeeping ends up
  longer than the regex translator.
- **`glob.glob` per pattern against the filesystem** — rejected: it re-walks the tree once per
  pattern, cannot express negation ordering, and makes matching depend on what exists on disk rather
  than on the path string.

## R2: Which gitignore semantics to implement, and where to diverge

**Decision**: Implement this subset, matched against the corpus-relative POSIX path:

| Construct | Behavior |
|---|---|
| `# comment`, blank line | skipped |
| trailing whitespace | stripped |
| `!pattern` | negation; re-admits a path an earlier rule excluded |
| trailing `/` | directory-only: matches a directory and everything beneath it |
| leading `/` | anchored at the corpus root |
| any interior `/` | anchored at the corpus root |
| no `/` at all | matches at any depth |
| `*` | any run of characters except `/` |
| `?` | one character except `/` |
| `**` | any number of path segments; `a/**/b` also matches `a/b` |
| ordering | last matching rule wins |

**Deliberate divergence from git**: git cannot re-include a file whose parent directory is excluded
("It is not possible to re-include a file if a parent directory of that file is excluded"). Spec
Acceptance Scenario 4 — `archive/` followed by `!archive/2024-decisions.md` — requires re-inclusion,
and that example comes from the issue itself. Rules are therefore evaluated **per candidate file**:
every rule is tested against the file's relative path and against each of its ancestor prefixes, and
the last rule that matches decides. A negation naming the file wins over an earlier directory rule.

Verified against real git rather than taken from the documentation — with `archive/` and
`!archive/2024-decisions.md` in `.gitignore`, `git status --untracked-files=all` reports only
`.gitignore`, so the negated file stays invisible:

```text
.gitignore:  archive/
             !archive/2024-decisions.md
git sees:    ['.gitignore']        # archive/2024-decisions.md NOT re-included
```

This has a second consequence that settles R1 independently: **`pathspec` could not satisfy spec
Acceptance Scenario 4 either**, because it faithfully reproduces git's limitation. The new dependency
would have bought semantics we must diverge from anyway.

The divergence is a semantic promise, not an accident, so it is documented in
[contracts/kgmdignore-format.md](./contracts/kgmdignore-format.md) and in the configuration
reference.

**Out of the subset** (documented as such, per spec Assumptions): character classes (`[a-z]`),
backslash escapes for literal `#`, `!`, or trailing space. A pattern using them matches literally,
which is the conservative failure — it excludes nothing rather than excluding too much.

**Alternatives considered**: full gitignore parity. Rejected — it drags in escape handling and the
re-inclusion limitation we specifically do not want, for constructs no motivating example uses.

## R3: Whether to prune the directory walk

**Decision**: Keep the existing `Path.rglob("*.md")` walk. Ignore rules filter the discovered list;
they do not prune traversal.

**Rationale**: Pruning traversal and supporting re-inclusion are mutually exclusive — if `archive/`
is never descended into, `!archive/2024-decisions.md` can never match. R2 chose re-inclusion because
the spec requires it. The cost being controlled here is provider spend (one model call per chunk),
not walk time; a directory walk is local, free, and already crosses dot-directories today, so this
is not a regression. `corpus.include` remains the tool for scoping the *walk* on a huge tree, and
`.kgmdignore` is the tool for controlling *spend*. That division is worth stating in the docs
because it is the question a user with a vendored `node_modules` will ask.

**Alternatives considered**: `os.walk` with in-place `dirnames` pruning and git's re-inclusion
limitation. Rejected: it trades a spec requirement for a saving on an operation that costs nothing.

## R4: Where the resolved file set is computed

**Decision**: One new function `ingest.scan_corpus_files(root, config) -> FileScan` composes the
three existing filters in a fixed order and is the single source of the resolved set. Both the
ingest path and the preview call it. `find_markdown_files` and `_is_dotpath` keep their current
signatures and roles.

Order (spec FR-007): `corpus.include` scopes candidates → `.kgmdignore` subtracts, negations re-add
→ dot-path exclusion applied last.

**Rationale**: Two code paths computing "what will be indexed" is how a preview drifts from reality.
`FileScan` returns the three groups (`included`, `ignored`, `dotpath`) so the preview can report
counts without recomputing anything. Composing rather than rewriting keeps the diff to
`find_markdown_files` at zero, which matters because FR-009 demands byte-identical behavior when no
ignore file exists.

**Alternatives considered**: threading ignore rules into `find_markdown_files` as a parameter.
Rejected: it would have to return the excluded groups too, so the include-scoping helper would grow
a second responsibility and every caller would pay for it.

## R5: Why the dot-path rule cannot be re-enabled by a negation

**Decision**: The dot-path filter stays a separate pass applied *after* ignore evaluation, exactly
as today (`ingest_documents` currently filters with `_is_dotpath` after discovery).

**Rationale**: Non-overridability (spec FR-008) is structural rather than a check to remember —
there is no code path by which a negation result reaches the dot-path decision. A single combined
rule list would make `!.kgmd/notes.md` a live risk, and `.kgmd/` contains the database and the
prompt overrides.

## R6: Clearing stale vectors is a correctness fix, not tidiness

**Decision**: Pruning MUST delete `vec_chunks` and `vec_entity_mentions` rows for the removed ids,
before deleting the `chunks` rows.

**Rationale**: This is a demonstrable data-corruption path, verified in source:

```python
# kgmd/embed.py:89-92
rows = conn.execute(
    """SELECT c.id, c.content FROM chunks c
       WHERE c.id NOT IN (SELECT chunk_id FROM vec_chunks)"""
).fetchall()
```

`chunks.id` and `entity_mentions.id` are plain `INTEGER PRIMARY KEY` (`kgmd/schema.py:36`, `:75`),
so SQLite reuses ids after deletes. The vec0 tables have no foreign key to cascade from. A stale
`vec_chunks` row therefore makes a *future, unrelated* chunk look already-embedded, and semantic
search then answers from the vector of text that no longer exists. `docs/guides/maintenance.md`
already documents this exact hazard for the `reset` path.

Deleting from a vec0 virtual table by primary key works, including with a subselect — probed against
`sqlite-vec` on this machine:

```text
DELETE FROM vec_chunks WHERE chunk_id IN (1, 3)                        -> remaining: [(2,)]
DELETE FROM vec_chunks WHERE chunk_id IN (SELECT id FROM chunks)       -> count: 0
```

**Alternatives considered**: leaving vectors and relying on a future clean rebuild. Rejected: it
makes the feature actively harmful — turning on an ignore rule would poison search for unrelated
notes.

## R7: What else must be removed, and what the cascades do not cover

**Decision**: Remove in this order, inside the existing ingest transaction:

1. Resolve orphan `documents.id` set (recorded path not in the resolved set).
2. Collect their `chunks.id`, then the `entity_mentions.id` on those chunks, and the `entity_id`
   values those mentions point at (needed in step 7).
3. `DELETE FROM vec_entity_mentions WHERE mention_id IN (...)`.
4. `DELETE FROM vec_chunks WHERE chunk_id IN (...)`.
5. `DELETE FROM relations WHERE evidence_chunk_id IN (...)` — **explicit**, because
   `relations.evidence_chunk_id` is `ON DELETE SET NULL` (`kgmd/schema.py:95`), so the rows would
   otherwise survive with null evidence and keep answering `kgmd relations` with no provenance
   (spec FR-013). The unique index includes `evidence_chunk_id`, so a relation independently
   extracted from a surviving chunk is a different row and is untouched.
6. `DELETE FROM chunks WHERE document_id IN (...)` — cascades to `entity_mentions`
   (`ON DELETE CASCADE`, `kgmd/schema.py:78`) — then `DELETE FROM documents`.
7. Sweep entities collected in step 2 that now have no mentions and no relations.

**Why step 7 exists**: spec SC-005 says an excluded note "appears in no query output". An entity
extracted only from an excluded note would otherwise still be listed by `kgmd entities` and
`kgmd find`. The sweep is scoped to entities touched by this prune, so it never collects the
pre-existing orphan entities that `extract --force` leaves behind — that is separate recorded debt
in `docs/guides/maintenance.md` and widening the blast radius here would be an unrequested behavior
change.

**Binding**: chunked `IN (...)` lists (batch 500) against SQLite's variable limit. A `TEMP TABLE`
would be simpler but issues DDL outside `kgmd/schema.py`, which Principle I prohibits.

## R8: The empty-resolved-set guard

**Decision**: Before any delete, if the resolved set is empty and `documents` is non-empty, raise
and change nothing.

**Rationale**: R7 makes pruning unconditional, so a single stray `*` in `.kgmdignore` would silently
delete an entire graph — a worse failure than the one this feature fixes. Fail fast with a
remediation hint, in the house style of `check_embedding_model` (`kgmd/db.py:50-54`).

The message must be quotable in `docs/guides/troubleshooting.md`: `test_quoted_errors_exist_in_source`
requires the single code span on each `**Symptom**:` line to appear verbatim in `kgmd/**/*.py`. So
the interpolated count goes in a later fragment and the leading fragment stays one contiguous string
literal that the doc can quote.

## R9: The preview surface

**Decision**: `kgmd build --dry-run`, with `--json` for machine output. `--json` without `--dry-run`
is rejected with a `ClickException`. Handled before `init_db`, so a dry run on a corpus with no
database creates nothing.

**Rationale**: There is no standalone `ingest` command (ingest runs inside `build` at
`kgmd/cli.py:223` and inside `extract` at `:285`), so the preview belongs on the command that does
the spending — "what would build do" is self-documenting and sits where the user is already typing.
Ordering before `init_db` matters: `init_db` creates `graph.db`, which would violate FR-017 for a
dry run on a fresh corpus. When the database is absent the removal count is reported as 0.

Doc-gate consequences, both satisfied by writing the docs: adding an `as_json` parameter puts `build`
into `structured_output_commands()`, so `test_structured_output_parity` requires a
`**Structured output**:` block in the `### build` section of `docs/reference/cli.md`, and
`test_all_parameters_documented` requires `` `--dry-run` `` and `` `--json` `` as code spans there.

**Alternatives considered**:

- **A new `kgmd files` command.** Cleaner as a read command, and `--json` needs no gating. Rejected:
  it adds a top-level surface, a `### files` doc section, and a Principle III question about whether
  a discovery command belongs in `kgmd/query.py` — for output that only ever matters immediately
  before a build.
- **`--json` implying `--dry-run`.** Rejected: `kgmd build --json` would then silently not build,
  which is the kind of surprise the constitution's fail-fast rule exists to prevent.

**MCP exclusion** (Principle III requires stating it): the preview is not added to
`kgmd/mcp_server.py`. It answers a filesystem-and-config question about work not yet done, for an
operator about to spend money; MCP tools read committed graph state for an assistant. The resolved
file set is not graph state, so it also gets no `kgmd/query.py` function — `query.py` remains the
sole read layer for the *graph*, and discovery stays in `ingest.py` where it already lives.

## R10: Module placement and the starter file

**Decision**: New leaf module `kgmd/ignore.py` — stdlib only, imported by `ingest.py` and `cli.py`,
importing nothing from the package. It also owns the starter-file template and its writer, so all
`.kgmdignore` knowledge lives in one place.

`kgmd init` writes `.kgmdignore` at the **corpus root** only when no such file exists, and every
line is a comment or blank so a fresh corpus indexes exactly what it indexes today (spec FR-019).

**Rationale**: Pattern compilation is a self-contained concern with a large unit-test surface; inside
`ingest.py` it would be half the module. Placing it as a leaf keeps the constitution's one-way
dependency direction intact (`ingest` → `ignore`, and `ignore` → nothing). No new subpackage is
created, which the constitution prohibits.

`.kgmdignore` sits at the corpus root rather than in `.kgmd/` because it is user-authored input that
users will want in version control beside their notes, and because the issue specifies that
location. It is configuration, not corpus state, so Principle I is not engaged — the same reasoning
that puts `.kgmd/config.yaml` outside `graph.db`.

**Alternatives considered**: keeping the writer next to `write_default_config` in `kgmd/config.py`.
Rejected: it would split `.kgmdignore` knowledge across two modules for one 12-line constant.

## R11: Documentation statements this change falsifies

**Decision**: Treat the following as part of the change, not follow-up. Each is a documented claim
that becomes false, and the docs gate gives no follow-up window.

| Location | Current claim | Why it breaks |
|---|---|---|
| `docs/guides/maintenance.md:63` | "File deleted from disk \| **nothing**" | Pruning now removes it |
| `docs/guides/maintenance.md:64` | "File renamed … the old path's data lingers" | No longer lingers |
| `docs/guides/maintenance.md:86-87` | orphaned entities need a full rebuild | Now swept on removal (scoped per R7) |
| `docs/examples/personal-notes.md:271-275` | "**Deleted notes are not removed from the graph.**" | Limitation is gone |
| `docs/examples/mcp-assistant.md:170` | "including entities extracted from notes you have since deleted" | No longer true |
| `docs/contributing/architecture.md:15` | `find_markdown_files` applies `corpus.include` and skips dotted paths | Must name the ignore pass and `scan_corpus_files` |
| `docs/reference/configuration.md:78` | `corpus.include` row | Must state the ignore interaction |

Additions: a `.kgmdignore` section in `docs/reference/configuration.md`; a spend-control mention
under `docs/guides/maintenance.md` → "Controlling provider spend"; `--dry-run` / `--json` rows plus a
`**Structured output**:` block in the `### build` section and the starter file in `### init` of
`docs/reference/cli.md`; a troubleshooting entry for the empty-resolved-set guard.

No new config key is introduced, so `DEFAULT_CONFIG` is untouched and the "Nineteen keys" count in
`docs/reference/configuration.md` stays correct — a direct benefit of rejecting `corpus.exclude`.

## R12: Test strategy under Principle V

**Decision**: Two new test modules, both hermetic.

- `tests/test_ignore.py` — pattern semantics as pure unit tests: comments, blanks, whitespace,
  anchoring, `*` not crossing `/`, `**` across depths, directory rules, negation ordering,
  re-inclusion inside an excluded directory, and unsupported constructs matching literally.
- `tests/test_ingest.py` — discovery and pruning over `tmp_path` / `tmp_corpus`: resolved set with
  and without an ignore file, `corpus.include` interaction, dot-path non-overridability, prune
  removes document/chunks/mentions/relations/vectors, prune idempotency, the empty-set guard, and
  the stale-vector regression (hand-packed `struct.pack` vectors per Principle V, asserting the
  `vec_chunks` row for a removed chunk is gone so a reused id cannot inherit it).

No model call is involved in either module — ingest and discovery do not touch the LLM boundary, so
no `litellm` patching is needed except where an existing fixture already provides it.
