# Phase 1 Data Model: Corpus Exclusions via `.kgmdignore`

**Feature**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

Two kinds of data appear here: **new in-memory structures** that carry ignore rules and the resolved
file set, and **existing database tables** whose rows this feature removes. No DDL changes, no schema
version bump, no new configuration key.

---

## 1. New in-memory structures

### `IgnoreRule` (frozen `@dataclass`, `kgmd/ignore.py`)

One parsed line of `.kgmdignore`.

| Field | Type | Meaning |
|---|---|---|
| `pattern` | `str` | the original text of the line, after stripping whitespace and any `!` prefix; kept for error messages and preview output |
| `regex` | `re.Pattern[str]` | compiled once at parse time; matched against a corpus-relative POSIX path |
| `negated` | `bool` | line began with `!`; a match re-admits the path |
| `dir_only` | `bool` | line ended with `/`; matches a directory and everything beneath it |
| `line_number` | `int` | 1-based line in `.kgmdignore`, for diagnostics |

**Validation rules**

- A line whose first non-whitespace character is `#` produces no rule.
- A blank or whitespace-only line produces no rule.
- Trailing whitespace is stripped before parsing; a lone `!` or `/` after stripping produces no rule.
- `regex` is fully anchored (`\A…\Z`). Anchoring at the corpus root vs. matching at any depth is
  baked into the compiled pattern, not decided at match time.
- Rule order is significant and is the file's order. `IgnoreRule` instances are never reordered or
  deduplicated.

### `Ignore ruleset` — `list[IgnoreRule]`

A plain list, not a wrapper class: order is the only invariant and a list already expresses it. An
absent `.kgmdignore` yields `[]`, which is what makes spec FR-009 (absent file behaves exactly as
today) hold by construction.

**State transitions**: none. The list is built from file text on every run and never mutated or
cached. Editing `.kgmdignore` between builds therefore takes effect on the next build with no
invalidation step.

### `FileScan` (frozen `@dataclass`, `kgmd/ingest.py`)

The resolved file set plus the reasons for every exclusion. This is the single value both ingest and
the preview consume, so the preview cannot drift from what a build would do.

| Field | Type | Meaning |
|---|---|---|
| `included` | `list[Path]` | absolute paths that will be indexed, sorted |
| `ignored` | `list[Path]` | absolute paths excluded by `.kgmdignore`, sorted |
| `dotpath` | `list[Path]` | absolute paths excluded by the dot-path rule, sorted |

**Validation rules**

- The three lists are disjoint, and their union is the candidate set produced by `corpus.include`
  scoping.
- Precedence is fixed and encoded in construction order (spec FR-007): `corpus.include` scopes the
  candidates → `.kgmdignore` moves paths into `ignored` → the dot-path rule moves paths into
  `dotpath`. Because the dot-path pass runs last and reads no rule state, no negation can move a
  path out of `dotpath` (FR-008).
- Paths are absolute; callers derive the corpus-relative form for display and for `documents.path`
  comparison, matching what `ingest_documents` already does.

---

## 2. Existing tables this feature removes rows from

No column, index, constraint, or `PRAGMA user_version` changes. The tables are listed with the
cascade behavior that decides whether a delete must be explicit.

| Table | Removal trigger | Cascade behavior | Explicit delete needed? |
|---|---|---|---|
| `documents` | recorded `path` is absent from `FileScan.included` | — | **Yes** — the orphan set is defined here |
| `chunks` | `document_id` in the orphan set | `ON DELETE CASCADE` from `documents` | Yes, issued before `documents` so ids can be collected first |
| `entity_mentions` | `chunk_id` in the removed chunks | `ON DELETE CASCADE` from `chunks` | No — the chunk delete covers it |
| `relations` | `evidence_chunk_id` in the removed chunks | `ON DELETE SET NULL` — **rows survive** | **Yes** (FR-013) |
| `entities` | lost their last mention in this prune and hold no relations | none — never cascaded | **Yes** (required by SC-005) |
| `vec_chunks` | `chunk_id` in the removed chunks | none — virtual table, no foreign keys | **Yes** (FR-012) |
| `vec_entity_mentions` | `mention_id` in the removed mentions | none — virtual table, no foreign keys | **Yes** (FR-012) |

### Why the two vec tables are the dangerous ones

`chunks.id` and `entity_mentions.id` are plain `INTEGER PRIMARY KEY`, so SQLite reuses their values
after deletes. `embed_new_chunks` selects `chunks` rows `WHERE c.id NOT IN (SELECT chunk_id FROM
vec_chunks)`. A stale `vec_chunks` row therefore makes a *future, unrelated* chunk look
already-embedded, and search then answers from the vector of text that no longer exists. Leaving
vectors behind would make this feature actively harmful to notes the user never excluded.

### Why relation rows are deleted rather than left with null evidence

`ON DELETE SET NULL` would keep a relation with no provenance, which contradicts the product's
provenance promise and leaves `kgmd relations` asserting something no chunk supports. The unique
index `(subject_id, predicate, object_id, evidence_chunk_id)` means a relation independently
extracted from a surviving chunk is a *different row*, so deleting the evidence-bound row never
loses an independently supported assertion.

### Why the entity sweep is scoped

Only entities whose mentions were removed by this prune are candidates, and only those left with no
mentions and no relations are deleted. A global sweep would also collect the pre-existing orphan
entities that `kgmd extract --force` leaves behind — separate recorded debt in
`docs/guides/maintenance.md`, and removing it here would be an unrequested behavior change.

---

## 3. Orphan removal: ordering and states

**Orphan** — an indexed document whose recorded `path` is absent from `FileScan.included`. The cause
is not recorded and does not matter: newly ignored, deleted, and renamed are the same state.

**Ordered sequence** (single transaction, inside the existing build lock):

```text
1. orphan_ids      <- documents whose path is not in included_relative_paths
2. if not orphan_ids            -> return zero counts, no writes
3. if included is empty and documents exist -> RAISE, no writes   (FR-015)
4. chunk_ids       <- chunks.id      WHERE document_id IN orphan_ids
5. mention_ids     <- entity_mentions.id WHERE chunk_id IN chunk_ids
6. entity_ids      <- entity_mentions.entity_id WHERE chunk_id IN chunk_ids
7. DELETE vec_entity_mentions WHERE mention_id IN mention_ids
8. DELETE vec_chunks          WHERE chunk_id   IN chunk_ids
9. DELETE relations           WHERE evidence_chunk_id IN chunk_ids
10. DELETE chunks             WHERE document_id IN orphan_ids     (cascades mentions)
11. DELETE documents          WHERE id IN orphan_ids
12. DELETE entities           WHERE id IN entity_ids
                              AND no remaining mention AND no remaining relation
```

**Invariants**

- Steps 4–6 collect ids **before** any delete; after step 10 the mention ids are unrecoverable.
- Step 3 precedes every write, so the guard cannot fire mid-prune and leave a partial graph.
- Steps 2 and 3 are the only early exits; both leave the database untouched.
- Re-running over an unchanged corpus takes the step-2 exit, which is what makes the operation
  idempotent (FR-014).
- Id lists are bound in batches of 500 to stay under SQLite's variable limit. A `TEMP TABLE` would
  be simpler but issues DDL outside `kgmd/schema.py`, which Principle I prohibits.

---

## 4. Reported counts

`ingest_documents` already returns `{"new", "updated", "skipped", "chunks_created"}`. Pruning adds
five keys, so the build summary can state what left the graph (FR-016):

| Key | Meaning |
|---|---|
| `documents_removed` | orphan `documents` rows deleted |
| `chunks_removed` | `chunks` rows deleted |
| `relations_removed` | `relations` rows deleted for missing evidence |
| `entities_removed` | entities swept for having no mention and no relation left |
| `vectors_removed` | `vec_chunks` + `vec_entity_mentions` rows deleted |

Existing keys keep their names and meanings, so the two current call sites
(`kgmd/cli.py` `build` and `extract`) continue to read the same fields.

---

## 5. What is deliberately not modelled

- **No `corpus.exclude` config key** (FR-020). `DEFAULT_CONFIG` is untouched, so the configuration
  reference's key count and its bidirectional coverage test are unaffected.
- **No cache of parsed rules.** Re-parsing a file of a few dozen lines once per run is free, and a
  cache would need an invalidation story for a file the user edits between runs.
- **No record of why a file was excluded** in the database. Exclusion is derived from the corpus
  directory plus config on every run; storing it would create corpus state outside `graph.db`.
- **No `mtime` or timestamp involvement.** Skip decisions stay content-hash driven (Principle IV);
  removal is driven by set difference, not by time.
