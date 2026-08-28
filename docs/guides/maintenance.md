# Maintaining a kgmd corpus
> Applies to kgmd 0.1.x

For anyone who already has a built graph and now has to keep it current. This page explains exactly
what a re-run repeats and what it skips, how to force full reprocessing, which stages spend provider
credit, how to reset or relocate a corpus, what the run log contains, and what the current lack of
schema migrations means for upgrades.

## What a re-run actually does

Two sha256 content hashes gate all the expensive work. Both are digests of a file's complete text
(`hash_content`, `kgmd/ingest.py`) and both live on the file's `documents` row:

| Column | Set by | Gates |
|---|---|---|
| `documents.content_hash` | ingest, on every change | whether the file is re-read, re-chunked, re-embedded |
| `documents.last_extracted_hash` | extraction, on success | whether the document is sent to the provider again |

Ingest walks the corpus root for `*.md`, drops any path with a dot-prefixed component (so `.kgmd/`,
`.git/`, and friends are never ingested), and optionally narrows the walk to `corpus.include`. For
each file it hashes the bytes and compares against the stored `content_hash`. Equal means the file is
counted as skipped and nothing else happens to it.

Extraction then selects only the documents where `last_extracted_hash` is `NULL` or differs from
`content_hash`. A document's watermark is written *after* the run, and only if at least one of its
chunks came back successfully — so a document whose every chunk failed stays queued for the next run
instead of being silently marked done.

`documents.mtime` is written on every ingest, but no code path ever reads it. Touching a file without
changing its bytes repeats nothing; rewriting bytes while preserving mtime is still picked up.

### What an edited file invalidates

When ingest finds a digest mismatch for a path it already knows, it updates `content_hash`,
`size_bytes`, `mtime`, and `ingested_at`, sets `last_extracted_hash` to `NULL`, and deletes every
`chunks` row for that document before re-chunking with the current `chunking.*` settings. Foreign
keys are on, so that chunk delete cascades:

- `entity_mentions.chunk_id` is `ON DELETE CASCADE` — the document's mentions go with its chunks.
- `relations.evidence_chunk_id` is `ON DELETE SET NULL` — relation rows **survive** with their
  evidence pointer cleared.
- `entities` rows are never deleted here. An entity that only ever appeared in text you removed stays
  in the graph.

The practical consequence: repeated edits accumulate relation rows whose evidence is `NULL`, because
the uniqueness index covers `(subject_id, predicate, object_id, evidence_chunk_id)` and the
re-extracted copy carries a fresh chunk id. If a corpus has been edited heavily over months, a clean
rebuild produces a tidier graph than an incremental one.

A second consequence is narrower but worth knowing. `chunks.id` is a plain `INTEGER PRIMARY KEY`, so
its values are reused: if the edited document happened to own the highest chunk ids in the table, the
replacement chunks are assigned those same ids. `embed_new_chunks` selects chunks with no row in
`vec_chunks`, so those chunks are skipped and keep the vectors of the text they replaced. Semantic
search over a heavily edited corpus is one more reason to prefer a periodic clean rebuild.

### Change made, work repeated

| Change made | Work repeated on the next `kgmd build` |
|---|---|
| Nothing | ingest skips every file, embedding finds nothing new, extraction selects no documents; resolution and induction still run in full |
| One file edited | that file re-hashed and re-chunked, its chunks re-embedded, its mentions cascade-deleted, the document re-extracted; resolution and induction full |
| New file added | new `documents` row, chunks created and embedded, document extracted; resolution and induction full |
| File deleted from disk | **nothing** — ingest only iterates files that exist, so the document, its chunks, and its entities stay in the graph |
| File renamed | treated as a delete plus an add: the old path's data lingers, the new path is ingested and extracted from scratch |
| `chunking.*` changed | nothing for unchanged files; their hashes still match, so old chunk boundaries persist |
| `llm.model` or a prompt changed | nothing; neither is hashed. Use `kgmd extract --force` |

Resolution and induction are not incremental at all. `kgmd resolve` re-clusters every embedded
mention in the database on each run, and `kgmd induce` regenerates the schema from full aggregate
statistics and appends a new `schema_versions` row, so the schema is versioned rather than mutated.

## Forcing full reprocessing

`kgmd extract --force` ignores both watermarks. It selects every document, and before collecting
chunks it deletes that document's `entity_mentions` rows and every `relations` row whose evidence
chunk belongs to it — so the previous extraction's output is cleared rather than layered over.

Reach for it when the *inputs to extraction* changed but the *files* did not:

- You edited `.kgmd/prompts/extract.txt`. Prompt overrides are read from disk on every run and are
  not part of any hash.
- You changed `llm.model`, `llm.temperature`, or `extraction.retry_on_parse_failure`.
- You suspect a bad extraction — a run where many chunks failed, or output that looks truncated.

`--force` does **not** re-chunk and does **not** re-embed: it works from the chunks already in the
database, and `entities` rows left with no remaining mentions are not swept up. To change chunk
boundaries or drop orphaned entities you need a full rebuild (see [Starting over](#starting-over)).

## Controlling provider spend

Only three stages talk to a model provider:

| Stage | Provider calls |
|---|---|
| extract | one per chunk, plus up to `extraction.retry_on_parse_failure` further calls for that chunk if the response will not parse or validate |
| resolve | one per candidate cluster of two or more distinct entities, and only while `resolution.llm_verify_clusters` is true; parse failures retry twice |
| induce | one per run, plus one corrective call if the returned schema omits an entity type or predicate that exists in the graph |

Everything else is local: ingest and chunking, all embedding while `embedding.backend` is `fastembed`
(the default, `BAAI/bge-small-en-v1.5`, 384 dimensions, no credential needed), every query command
including `kgmd find` — which embeds your query locally — plus `kgmd export`, `kgmd stats`, and
`kgmd schema`. Setting `embedding.backend` to `litellm` moves embedding onto the provider too.

Settings that change call volume:

| Setting | Effect on volume |
|---|---|
| `chunking.max_chars` | extraction calls scale with chunk count; larger chunks mean fewer, bigger calls |
| `resolution.llm_verify_clusters` | `false` removes the resolution stage's calls entirely, at the cost of merging on cosine similarity alone |
| `resolution.similarity_threshold` | a higher threshold produces fewer multi-member clusters, so fewer verification calls |
| `llm.concurrency` | worker threads during extraction; changes wall-clock time and burst rate, not the number of calls |

Two divergences worth knowing before you tune:

- `llm.max_tokens` defaults to `16384` in config, but the extraction stage passes its own local
  default of `4096`, so raising the config key may not raise the limit actually used.
- Resolution verification calls only take `llm.model` from config. Their token limit, timeout, and
  retry count come from the library defaults, not from `llm.max_tokens`, `llm.timeout_seconds`, or
  `extraction.retry_on_parse_failure`.

Trial-run before committing a large corpus. Either initialize a throwaway corpus in a small
subdirectory and build that, or set `corpus.include` to one directory so ingest only walks that
subtree, then read `kgmd stats` and the run log to project cost. Full key reference:
[../reference/configuration.md](../reference/configuration.md).

## Starting over

There are three levels, and in 0.1.0 only the third one works — see the warning below.

| Action | Removes | Preserves |
|---|---|---|
| `kgmd reset` | relations, mentions, entities, schema versions, extraction and resolution run history; clears `last_extracted_hash` on every document; truncates `.kgmd/logs/build.log` | `documents` and `chunks` rows, chunk embeddings, `.kgmd/config.yaml`, `.kgmd/prompts/` |
| `kgmd reset --hard` | everything above, plus all `chunks` and `documents` rows | `.kgmd/config.yaml`, `.kgmd/prompts/`, the database file and its schema |
| delete `.kgmd/graph.db` | the entire database: schema, data, embeddings, and the recorded embedding model | `.kgmd/config.yaml`, `.kgmd/prompts/`, your markdown |

`kgmd reset` prompts for confirmation; `--yes` skips the prompt. It requires the database to exist
and takes the build lock while it works.

> **Both `reset` forms fail in 0.1.0.** The command issues its `DELETE` statements and then runs
> `conn.execute("VACUUM")` on the same connection, which SQLite refuses inside the open transaction
> the deletes started. The command exits 1 with `Error: cannot VACUUM from within a transaction` and,
> because the transaction is never committed, changes nothing. Until this is fixed, delete
> `.kgmd/graph.db` and rebuild.

Deleting the database file is also the safest reset for a second reason. Neither `reset` form deletes
rows from the `vec_chunks` and `vec_entity_mentions` virtual tables, and both `chunks.id` and
`entity_mentions.id` are plain `INTEGER PRIMARY KEY` columns whose values are reused once the tables
are emptied. Stale vectors would therefore be keyed to the ids that fresh chunks and mentions
receive, and `embed_new_chunks` skips any chunk that already has a row in `vec_chunks` — so search
and clustering would run against vectors belonging to deleted text.

```bash
rm -f .kgmd/graph.db .kgmd/graph.db-wal .kgmd/graph.db-shm
kgmd build .
```

`kgmd build` recreates the file and the schema on the next run, so there is no need to re-run
`kgmd init`. Note that a rebuild re-extracts every document and re-spends the full extraction budget.

## Changing the embedding model

Not supported in place. `kgmd build` and `kgmd extract` call `check_embedding_model` before
embedding, which compares `embedding.model` against the value written into the `kv` table at
initialization and raises if they differ. The message states the remedy directly: changing embedding
models mid-corpus is not supported in v1, and to re-embed you delete `.kgmd/graph.db` and rebuild.

The restriction is structural, not a policy choice. `init_db` creates the two `sqlite-vec` virtual
tables with a literal `FLOAT[dim]` column width taken from the embedder's dimension, and seeds
`embedding_dim` and `embedding_model` into `kv` — but only when `PRAGMA user_version` is `0`, i.e.
only for a brand-new file. Vector width and model identity are baked in at that moment and there is
no code that widens or re-embeds them afterwards.

So: change `embedding.model` in config *and* delete `.kgmd/graph.db` in the same step, then rebuild.
Changing one without the other either errors out or leaves vectors from the wrong model in place.

## Two builds at once

`build`, `extract`, `resolve`, `induce`, and `reset` all wrap their work in an exclusive `fcntl` lock
on `.kgmd/build.lock`, and the holder writes its PID into the file. Query commands take no lock, so
you can read the graph while a build runs.

The second process attempts a non-blocking lock, and on failure reads the PID from the file:

- **PID is alive** — it fails with `Another kgmd build process (PID 12345) is running. If this is
  stale, delete .kgmd/build.lock`.
- **PID is dead or unparseable** — the lock is treated as stale and reclaimed. The second process
  then waits for the kernel lock and proceeds, so no manual cleanup is needed.
- **File exists but is empty** — it fails with a variant of the same message pointing at
  `.kgmd/build.lock`.

On exit, the holder truncates the file, releases the lock, and unlinks it — including when the build
raises. A file left behind after a kill is harmless because of the stale-PID reclaim above; the only
case that needs your hand is an empty lock file, and the fix is to delete it:

```bash
rm -f .kgmd/build.lock
```

Verify no build is actually running before you delete it. The lock is `fcntl`-based, which means it
is per-file and enforced by the local kernel — it does not protect a corpus shared over NFS or a
sync service, so avoid building the same corpus from two machines.

## The run log

`.kgmd/logs/build.log` is a plain append-only text file. One line is written per provider *attempt*
by the extraction stage:

```text
[OK] model=openrouter/anthropic/claude-sonnet-4-5 prompt_chars=5312 resp_chars=1841 elapsed=6.42s
[FAIL] model=openrouter/anthropic/claude-sonnet-4-5 prompt_chars=5312 resp_chars=213 elapsed=3.10s
```

That is the whole record: outcome, model id, total prompt character count, response character count,
and elapsed seconds. On a `[FAIL]` line `resp_chars` is the length of the error text, not of a model
response.

What is **never** written: note content, chunk text, prompts, model responses, entity names, file
paths, and credentials. Logging is also best-effort — the writer swallows its own exceptions, so an
unwritable log never fails a build.

Two gaps to be aware of when reading it:

- Resolution verification calls are made without a log path and do not appear. Induction calls the
  provider directly and does not appear either. Extraction is the only logged stage.
- `kgmd reset` truncates the file, so the log covers only work since the last reset.

For per-chunk failure detail beyond the log, re-run with `--debug`; see
[troubleshooting.md](./troubleshooting.md).

## Backup and relocation

A corpus is self-contained and portable: the markdown files plus the `.kgmd/` directory beside them.
`documents.path` is stored relative to the corpus root, so moving or renaming the enclosing directory
does not invalidate anything.

The database is a single SQLite file, `.kgmd/graph.db`, opened in WAL mode. That means up to two
sidecar files, `graph.db-wal` and `graph.db-shm`, may exist alongside it and are part of the live
state. Copy all three, or — better — copy while no kgmd process is running, when the WAL has been
checkpointed and the sidecars are disposable.

```bash
tar czf notes-backup.tar.gz notes/
```

Skip `.kgmd/build.lock` if it happens to exist: it holds a PID from the source machine and is
recreated on demand. `.kgmd/config.yaml` and `.kgmd/prompts/` are the two files worth keeping under
version control; `graph.db` is derived state that a rebuild can regenerate from the markdown, at the
cost of re-spending the extraction budget.

## Upgrading kgmd

There is no migration path in 0.1.0, and this is a limitation rather than a guarantee of stability.
`init_db` reads `PRAGMA user_version`; when it is `0` the full schema is created and the version set
to `1`, and when it is anything else the function returns the open connection untouched. No code
inspects the version further and no upgrade steps exist.

Consequences for a version bump:

- Within 0.1.x, an existing `.kgmd/graph.db` opens as-is.
- If a future release changes the schema, an old database will be opened without being upgraded, and
  the fix will be to delete `.kgmd/graph.db` and rebuild — the same recovery as an embedding-model
  change.
- Your markdown is the durable artifact. Keep `.kgmd/config.yaml` and any prompt overrides in version
  control so a rebuild reproduces the same configuration.

Check what you are running and what the graph currently holds before and after an upgrade:

```bash
kgmd --help
kgmd stats
```

For the meaning of every field `kgmd stats` reports, see
[../reference/cli.md](../reference/cli.md).
