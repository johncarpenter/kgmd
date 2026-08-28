# Feature Specification: Corpus Exclusions via `.kgmdignore`

**Feature Branch**: `002-kgmdignore-exclusions`

**Created**: 2026-08-28

**Status**: Draft

**Input**: User description: "gh issue 3 - add a kgmdignore capability" — GitHub issue #3, "Add a .kgmdignore file to exclude paths from indexing"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Exclude a folder from indexing (Priority: P1)

A user keeps a notes directory that contains material with no knowledge-graph value: an `archive/`
folder of superseded notes, a `drafts/` folder of half-written thoughts, a vendored documentation
tree, and a set of `*-template.md` boilerplate files. Today the only way to keep those out of the
graph is to list *every other* directory in the `corpus.include` allowlist and keep that list in
sync as the corpus grows — and a new folder added outside the list is silently never indexed.

The user instead creates a `.kgmdignore` file at the corpus root, writes the paths and patterns to
skip, and runs a build. The excluded material is not read, not chunked, not sent to the language
model, and does not appear in the graph. Everything else is indexed exactly as before.

**Why this priority**: This is the feature. Every indexed file costs money — one model call per
chunk — so indexing an archive or a template folder is direct, repeated spend that buys nothing and
pollutes entity resolution with junk mentions. Without this story there is no way to subtract
anything from a corpus.

**Independent Test**: Create a temporary corpus with files inside and outside the ignored paths, add
a `.kgmdignore`, and assert the resolved set of files to be indexed contains exactly the expected
paths. Fully testable with no model access and no network.

**Acceptance Scenarios**:

1. **Given** a corpus containing `notes/a.md` and `archive/b.md`, **When** `.kgmdignore` contains
   `archive/`, **Then** the resolved file set is exactly `notes/a.md`.
2. **Given** a corpus containing `docs/CHANGELOG.md` and `docs/guide.md`, **When** `.kgmdignore`
   contains `**/CHANGELOG.md`, **Then** `docs/guide.md` is indexed and `docs/CHANGELOG.md` is not.
3. **Given** a `.kgmdignore` whose lines include blank lines, lines starting with `#`, and lines
   with surrounding whitespace, **When** a build runs, **Then** comments and blank lines are ignored
   and the remaining patterns take effect.
4. **Given** `.kgmdignore` containing `archive/` followed by `!archive/2024-decisions.md`,
   **When** a build runs, **Then** `archive/2024-decisions.md` is indexed and every other file
   under `archive/` is not.
5. **Given** no `.kgmdignore` file at the corpus root, **When** a build runs, **Then** the resolved
   file set is identical to the set produced before this feature existed.
6. **Given** a corpus with `corpus.include: ["notes"]` in configuration and `.kgmdignore`
   containing `notes/archive/`, **When** a build runs, **Then** the allowlist scopes the scan to
   `notes` and the ignore rules subtract `notes/archive/` from it.
7. **Given** `.kgmdignore` containing `!.kgmd/graph-notes.md` or `!.git/README.md`, **When** a build
   runs, **Then** dot-prefixed paths remain excluded — the negation cannot re-admit them.

---

### User Story 2 - Newly-excluded material leaves the graph (Priority: P2)

A user has already built a graph over a corpus. They now add a `.kgmdignore` that excludes
`archive/`. They expect those notes to stop answering searches. The same user has also deleted and
renamed notes over time and expects the graph to reflect that.

After the next build, documents that are no longer part of the resolved file set — because they were
newly ignored, deleted, or renamed — are gone from the graph, along with everything derived from
them: their text chunks, the entity mentions found in them, and their search vectors.

**Why this priority**: Without this, the feature is a no-op for every corpus that already exists.
The ignored notes, their chunks, their mentions, and their embeddings stay in the single durable
artifact and keep answering queries, so the user sees no behavioral change and reasonably concludes
the ignore file does not work. It is P2 rather than P1 only because Story 1 alone delivers value for
a corpus built after the ignore file exists.

**Independent Test**: Build a graph over a seeded corpus, add an ignore rule covering one document,
re-build, and assert that document, its chunks, its mentions, and its vector rows are absent while
the untouched documents and their derived rows are unchanged.

**Acceptance Scenarios**:

1. **Given** an existing graph containing `archive/old.md` and its derived chunks, mentions, and
   vectors, **When** `.kgmdignore` gains `archive/` and a build runs, **Then** the document row, its
   chunks, its entity mentions, and its vector rows are all removed.
2. **Given** an existing graph, **When** a note is deleted or renamed on disk and a build runs,
   **Then** the record for the old path and all state derived from it is removed.
3. **Given** a relation whose supporting evidence came from a chunk of a now-removed document,
   **When** the removal completes, **Then** no relation is left pointing at evidence that no longer
   exists.
4. **Given** a corpus where removal has already happened, **When** the build is re-run with no
   changes, **Then** nothing further is removed and the reported counts show no work done.
5. **Given** an existing non-empty graph, **When** the ignore rules would resolve to an empty file
   set (for example a stray `*` pattern), **Then** the build stops with an actionable message and
   removes nothing.
6. **Given** an existing graph and a file whose content is unchanged and which remains un-ignored,
   **When** a build runs, **Then** that document is skipped exactly as before and no re-extraction
   is triggered.

---

### User Story 3 - Preview what will be indexed before spending (Priority: P3)

A user has written several ignore patterns and wants to know whether they did it right before paying
for a build. They ask for a preview and see the exact list of files that would be indexed, the count
of files, and the count excluded — with nothing written to the graph and no model calls made.

**Why this priority**: Ignore rules are otherwise unverifiable guesswork; a wrong pattern is
discovered only after the spend it was supposed to prevent. It is P3 because Stories 1 and 2 are
correct and useful without it.

**Independent Test**: Run the preview against a temporary corpus with an ignore file and assert the
printed/returned file list matches expectation and that the graph is byte-for-byte unmodified.

**Acceptance Scenarios**:

1. **Given** a corpus with a `.kgmdignore`, **When** the user requests a preview, **Then** the
   resolved file set is reported and no document, chunk, mention, or vector is created, updated, or
   removed.
2. **Given** a preview request, **When** it completes, **Then** no language-model call is made.
3. **Given** a preview request, **When** the user asks for machine-readable output, **Then** the
   resolved file set and counts are available as structured data.

---

### Edge Cases

- **No ignore file**: behavior is exactly as before this feature — no warning, no new output.
- **Empty ignore file, or one containing only comments and blank lines**: treated as no rules.
- **Rules exclude everything**: on an existing non-empty graph the build stops with an actionable
  message and removes nothing, rather than silently emptying the graph. On an empty graph it reports
  zero files to index.
- **Negation that re-admits a dot-prefixed path**: refused; the dot-path rule is applied last and is
  not overridable.
- **Ignore file placed in a subdirectory**: only the corpus-root file is read; nested ignore files
  are not consulted and this is documented.
- **Unreadable or non-UTF-8 ignore file**: build fails fast with a message naming the file and the
  remediation, rather than silently indexing everything.
- **Pattern written with a leading separator** (`/archive/`): anchored to the corpus root, not
  matched at every depth.
- **Pattern that matches a directory name mid-path** (`node_modules/`): excludes the whole subtree
  wherever it appears, unless anchored.
- **Ignore file edited between builds**: re-evaluated from disk on every run; no cached rule state.
- **A file both allowed by `corpus.include` and matched by an ignore rule**: excluded — ignore
  subtracts from the allowlist.
- **A file matched by an ignore rule but outside `corpus.include`**: already excluded; no error, no
  duplicate reporting.
- **Trailing whitespace and CRLF line endings in the ignore file**: tolerated.

## Requirements *(mandatory)*

### Functional Requirements

**Rule source and syntax**

- **FR-001**: The system MUST read exclusion rules from a single `.kgmdignore` file at the corpus
  root, matching patterns against corpus-relative paths using `/` as the separator regardless of
  host platform.
- **FR-002**: The system MUST ignore blank lines, lines whose first non-whitespace character is `#`,
  and surrounding whitespace on each rule.
- **FR-003**: The system MUST support directory-only rules, written with a trailing `/`, which
  exclude the entire subtree beneath the matched directory.
- **FR-004**: The system MUST support glob rules covering single-segment wildcards (`*`, `?`),
  multi-segment wildcards (`**`), and root-anchoring via a leading `/`. An unanchored pattern with no
  separator MUST match at any depth.
- **FR-005**: The system MUST support negation rules prefixed with `!` that re-admit a path excluded
  by an earlier rule, resolved in file order with the last matching rule winning.
- **FR-006**: The system MUST fail with an actionable message naming the file when `.kgmdignore`
  exists but cannot be read or decoded, rather than proceeding as if it were absent.

**Precedence and compatibility**

- **FR-007**: The system MUST apply exclusion in this order: the `corpus.include` allowlist scopes
  the candidate set (behavior unchanged), then `.kgmdignore` rules subtract from it with negations
  re-adding, then the existing dot-prefixed-path exclusion is applied last.
- **FR-008**: The system MUST keep the dot-prefixed-path exclusion non-overridable: no ignore or
  negation rule may cause a path containing a dot-prefixed component to be indexed.
- **FR-009**: The system MUST produce, when no `.kgmdignore` exists, exactly the file set it
  produced before this feature — no change in discovery, ordering, counts, or output.
- **FR-010**: The system MUST document and cover by test the combined case where both
  `corpus.include` and `.kgmdignore` are present.

**Removing material that is no longer part of the corpus**

- **FR-011**: The system MUST remove from the graph every document whose path is no longer in the
  resolved file set — whether it became ignored, was deleted, or was renamed.
- **FR-012**: Removal MUST also clear all state derived from that document: its chunks, the entity
  mentions in those chunks, and the search vectors for both, leaving no vector row that could later
  bind to an unrelated record.
- **FR-013**: Removal MUST NOT leave a relation asserting evidence from a chunk that no longer
  exists.
- **FR-014**: Re-running a build after removal MUST remove nothing further and MUST report no work,
  and MUST NOT re-extract documents whose content is unchanged.
- **FR-015**: When the resolved file set is empty and the graph is not, the system MUST stop with an
  actionable message and MUST NOT remove anything.
- **FR-016**: Removal counts MUST be reported in the build summary so the user can see what left the
  graph.

**Preview**

- **FR-017**: Users MUST be able to preview the resolved file set — the paths that would be indexed,
  plus counts of included and excluded files — without creating, updating, or removing any graph
  state and without any language-model call.
- **FR-018**: The preview MUST offer machine-readable output alongside its human-readable rendering.

**Starter file and documentation**

- **FR-019**: Corpus initialization MUST write a starter `.kgmdignore` whose every line is a comment
  or blank, so a freshly initialized corpus indexes exactly what it does today.
- **FR-020**: The system MUST NOT introduce a second mechanism for the same job: no
  `corpus.exclude` configuration key is added.
- **FR-021**: Documentation MUST be updated in the same change: a `.kgmdignore` reference section
  covering syntax, precedence, and the removal behavior; a spend-control mention in the maintenance
  guide; and command reference entries for any new user-facing option. The documentation coverage
  gate MUST pass in both directions.
- **FR-022**: The feature MUST NOT add a runtime dependency, or MUST justify one per the project's
  dependency rule.

### Key Entities

- **Ignore ruleset**: the ordered list of rules parsed from the corpus-root `.kgmdignore`. Ordered,
  because the last matching rule decides. Absent file means an empty ruleset.
- **Ignore rule**: one line — a pattern, whether it is negated, whether it is directory-only, and
  whether it is root-anchored.
- **Resolved file set**: the corpus-relative paths that will be indexed, after allowlist scoping,
  ignore subtraction, negation re-admission, and the dot-path exclusion. This is the value the
  preview reports and the value pruning compares against.
- **Orphan**: an indexed document whose path is absent from the resolved file set. Orphans and
  everything derived from them are removed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user excludes a subtree by adding one line to one file; the indexed file count drops
  by exactly the number of markdown files in that subtree and no other file's indexing status
  changes.
- **SC-002**: Excluded files generate zero language-model calls and zero spend on every subsequent
  build, measured by call count attributable to those files being 0.
- **SC-003**: A corpus with no `.kgmdignore` produces an identical indexed file set and identical
  build counts before and after this change — verified as a regression check, not by inspection.
- **SC-004**: A user can see the complete list of files a build would index, before any spend, in
  under 5 seconds on a 1,000-file corpus.
- **SC-005**: A note that becomes excluded returns zero search results and appears in no query
  output after the next build.
- **SC-006**: Every new user-facing surface introduced by this change has a documentation entry, and
  every documentation entry names something that exists — both directions enforced by the test gate.
- **SC-007**: The exclusion behavior is covered by tests that run with no network access and no model
  downloads, and pass on every supported runtime version.

## Assumptions

- **Gitignore-familiar semantics are what users expect.** The file name promises them, so the
  supported syntax is the common subset: comments, blank lines, `*`/`?`/`**` globs, trailing-`/`
  directory rules, leading-`/` anchoring, and `!` negation with last-match-wins ordering. Rarely used
  gitignore corners (character classes such as `[a-z]`, escaped literal `#`/`!`/spaces) are treated
  as out of scope for this change and documented as such.
- **Negation is in scope.** The issue permits declaring it out of scope, but the motivating example
  uses it and last-match-wins ordering is implementable without a new dependency.
- **One root-level file only.** Nested per-directory ignore files are out of scope; the corpus root
  is the single source of rules.
- **Pattern matching is case-sensitive**, matching gitignore behavior on a case-sensitive
  filesystem, regardless of the host filesystem's own case sensitivity.
- **Pruning is unified rather than ignore-specific.** Comparing the resolved file set against
  recorded document paths handles newly-ignored, deleted, and renamed files with one mechanism.
  Detecting "newly ignored" specifically would be strictly more work for strictly less coverage, so
  the issue's optional split is not taken and the "document the limitation instead" escape is not
  used.
- **The ignore file is the only exclusion mechanism.** No inline configuration key is added, so no
  new configuration key needs documenting and there is only one place to look when a file is missing
  from the graph.
- **`corpus.include` keeps its current literal-path behavior.** Its lack of glob support is a
  separate defect and is not fixed here.
- **Reusing `.gitignore` is out of scope.** A toggle to honor the repository's own ignore file
  conflates two concerns and belongs in a follow-up.
- **Only markdown files are candidates**, unchanged from today; ignore rules narrow that set and
  never widen it.
- **The preview surfaces on the existing build path** rather than as a new top-level command, since
  there is no standalone ingest command today.

## Dependencies

- The existing graph store's removal behavior: discarding a note's text automatically discards the
  entity mentions found in it, but it does not clear that note's search vectors and it leaves
  relations asserting evidence that no longer exists. Removal must therefore clear those explicitly,
  or stale search results and unsupported relations survive the removal.
- The documentation coverage gate, which fails the test suite if a new user-facing surface is
  undocumented or a documented surface does not exist.
- The project's offline test conventions — temporary-directory corpora, a mocked model boundary, and
  pre-computed search vectors — which this feature's tests must follow.

## Out of Scope

- A `corpus.exclude` configuration key or any second exclusion mechanism.
- Honoring `.gitignore`, or any toggle to do so.
- Glob support for `corpus.include`.
- Per-directory (nested) ignore files.
- Gitignore character classes and escape sequences.
- Following symbolic links during discovery; current behavior is unchanged.
