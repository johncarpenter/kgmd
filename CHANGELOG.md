# Changelog

All notable changes to kgmd are recorded here. Versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html), and the version number lives in
`kgmd/__init__.py`.

## 0.2.0 — 2026-08-28

### Added

- **`.kgmdignore`** — a gitignore-style file at the corpus root that excludes paths from indexing.
  Supports `#` comments, blank lines, `*` (never crossing `/`), `?`, `**`, trailing-`/` directory
  rules, leading-`/` anchoring, and `!` negation resolved last-match-wins. Because every indexed file
  is chunked and each chunk is one model call, this is the cheapest control over build spend. See
  [the configuration reference](docs/reference/configuration.md).
- **`kgmd build --dry-run`** — reports the files a build would index, the counts excluded by
  `.kgmdignore` and by the dot-path rule, and how many indexed documents would be removed. Takes no
  build lock, makes no provider call, and creates no database. `--json` gives the machine-readable
  form and requires `--dry-run`.
- **`kgmd init` writes a starter `.kgmdignore`** at the corpus root, every line commented so a fresh
  corpus indexes exactly what it did before. An existing file is never overwritten.

### Changed

- **Ingest now reconciles the graph against the corpus.** A document whose recorded path is no longer
  in the resolved file set is removed, along with its chunks, its mentions, relations whose evidence
  came from it, its rows in both vector tables, and any entity it leaves with no mention and no
  relation. Deleted, renamed, and newly-excluded files are one state and are handled identically.
  This applies to `kgmd build` and `kgmd extract`, which share the ingest path.

  **Upgrade note:** the first build after upgrading from 0.1.x may perform a large one-off removal on
  a corpus with a long edit history. Run `kgmd build --dry-run` first to see the count. The schema is
  unchanged — `PRAGMA user_version` is still `1` — so no migration is required.
- Ingest summaries in `kgmd build` and `kgmd extract` print a `Removed:` line when documents left the
  graph, and stay silent when none did.

### Fixed

- **A deleted or renamed note is no longer stranded in the graph.** Previously ingest only inserted
  and updated rows for files it found, so a note deleted from disk kept answering queries
  indefinitely. This was documented as a limitation rather than fixed.
- **Stale vectors no longer survive a removal.** `chunks.id` and `entity_mentions.id` are reused by
  SQLite after deletes, and `embed_new_chunks` skips any chunk that already has a vector row, so a
  leftover vector would silently bind to an unrelated future chunk and search would answer from
  deleted text. Both `sqlite-vec` tables are now cleared for removed ids.
- **Relations no longer survive with missing evidence.** `relations.evidence_chunk_id` is
  `ON DELETE SET NULL`, so relations bound to a removed chunk previously persisted with no
  provenance. They are now deleted.
- Two pre-existing `E501` violations in `kgmd/resolve.py` and `tests/test_resolve.py` that were
  failing `ruff check` on `main`, plus pending `ruff format` drift in `kgmd/llm.py` and
  `tests/test_docs.py`.
- `README.md` pointed the development clone at a repository URL that does not exist.

### Safety

- An ignore ruleset that resolves to an empty file set while the graph still holds documents aborts
  the build **before any write**, rather than emptying the graph. A stray `*` is a mistake, not an
  instruction.

### Notes

- No new runtime dependency. The pattern matcher is stdlib-only: `fnmatch`'s `*` crosses `/`, and
  `PurePath.match` is right-anchored with single-segment `**` on Python 3.10–3.12, so neither can
  express these semantics. `pathspec` was also rejected on merit — it reproduces git's refusal to
  re-include a file inside an excluded directory, which kgmd deliberately allows.
- No new configuration key. `corpus.exclude` was rejected rather than shipping two mechanisms for one
  job.
- **One deliberate divergence from `.gitignore`:** `archive/` followed by
  `!archive/2024-decisions.md` re-includes that file. git refuses this.

### Known issues

- `kgmd reset` and `kgmd reset --hard` remain broken: both run `VACUUM` inside the transaction their
  deletes opened, so the command exits 1 and changes nothing. Neither clears the vector tables, and
  `kgmd extract --force` leaves stale mention vectors that can corrupt entity resolution. Tracked in
  [#4](https://github.com/johncarpenter/kgmd/issues/4); deleting `.kgmd/graph.db` and rebuilding
  remains the only complete reset.
- Entities stranded by an earlier `kgmd extract --force` are still not swept. The new sweep is scoped
  to entities that a document removal itself orphaned.
- The three inert configuration keys (`extraction.max_entities_per_chunk`,
  `extraction.max_relations_per_chunk`, `induction.include_attribute_summary`) still have no read
  site.

## 0.1.0 — 2026-05-09

Initial release. Extraction, entity resolution, and schema induction over a directory of markdown
files, stored in a single SQLite file with `sqlite-vec` vector indexes, queryable from the CLI and
from an MCP server. Includes the `docs/` set and the documentation coverage gate.
