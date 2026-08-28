# Concepts
> Applies to kgmd 0.2.x

For anyone about to run, tune, or debug a build. This page defines the six words the rest of the
documentation uses without explanation — document, chunk, entity, mention, relation, induced schema —
explains what each pipeline stage reads and writes, and shows where all of it is stored.

## The pipeline

`kgmd build` runs six numbered stages in one locked pass. Three of them call the LLM; the rest are
local work.

```text
markdown files
     |
     |  ingest .......... sha256 + chunking .............. no LLM
     v
documents, chunks
     |
     |  embed chunks .... vector index over chunk text ... no LLM
     v
vec_chunks
     |
     |  EXTRACT ......... one LLM call per chunk ......... LLM
     v
entities, entity_mentions, relations
     |
     |  embed mentions .. vector index over surface forms  no LLM
     v
vec_entity_mentions
     |
     |  RESOLVE ......... cluster, then verify merges .... LLM (optional)
     v
merged entities
     |
     |  INDUCE .......... one summary call over the graph  LLM
     v
schema_versions
```

The three named stages are the ones with their own commands, and each is separately re-runnable
against an existing database.

**extract** — `kgmd extract`. Ingests first, then reads the `chunks` of every document whose
`last_extracted_hash` differs from its `content_hash`, so unchanged files cost nothing. It sends one
LLM call per chunk, `llm.concurrency` calls in flight at a time, and each call is given the corpus's
most common entity types and predicates as a vocabulary hint — refreshed every ten completed chunks,
so the vocabulary converges as the run proceeds rather than being fixed up front. Writes `entities`,
`entity_mentions` and `relations`, plus one row in `extraction_runs`. A document is only marked
extracted if at least one of its chunks succeeded. `kgmd extract --force` clears prior extractions
and re-extracts every document.

**resolve** — `kgmd resolve`. Reads `entity_mentions` joined to their vectors in
`vec_entity_mentions`; it needs extraction to have run and mentions to have been embedded. Mentions
are grouped by entity type and clustered with union-find over cosine similarity at or above
`resolution.similarity_threshold`, with clusters capped at `resolution.max_cluster_size`. Each cluster
spanning two or more entities is then sent to the LLM, which may split it into several partitions or
confirm one — set `resolution.llm_verify_clusters` to `false` to skip that call and merge every
cluster as-is. Merging re-points mentions and relations to the surviving entity, merges attributes,
deletes duplicate relations, and deletes the dropped entities. Writes one row in `resolution_runs`.
No new entities are created; resolution only removes.

**induce** — `kgmd induce`. Reads aggregate statistics over `entities` and `relations`: type counts,
attribute frequencies, predicate counts, and the subject-type/object-type pairs each predicate is used
with. It never sees your chunk text. One LLM call produces a YAML schema; if that schema omits an
entity type or predicate that exists in the database, kgmd re-prompts once with the missing names.
Writes one row in `schema_versions`. Returns early without an LLM call when the graph has no entities.

Both `kgmd extract` and `kgmd build` ingest before extracting, so you never call an ingest step
directly. Running `kgmd resolve` or `kgmd induce` alone skips straight to that stage against whatever
is already in the database.

One difference worth knowing: `kgmd resolve` and `kgmd induce` receive the corpus directory and so
honour per-corpus prompt overrides, while the resolve and induce stages inside `kgmd build` do not
receive it and use the bundled prompts. Extraction honours the override either way. See
[Prompts are yours](#prompts-are-yours) below.

## One file holds everything

There is one database: `.kgmd/graph.db`, a single SQLite file holding documents, chunks, entities,
mentions, relations, run history, induced schemas, and both vector indexes. There is no cache
directory, no sidecar index, no global state. Copying that file copies the graph; deleting it is a
complete reset.

The rest of `.kgmd/` is small and mostly yours:

| Path | Created by | Contents |
|---|---|---|
| `.kgmd/graph.db` | `kgmd init` | The entire graph, plus its vector indexes. |
| `.kgmd/config.yaml` | `kgmd init` | Corpus-level configuration, deep-merged over the global config. |
| `.kgmd/prompts/` | `kgmd init` (empty) | Optional prompt overrides. |
| `.kgmd/logs/build.log` | first LLM call | One append-only line per call: status, model, prompt and response character counts, elapsed seconds. No prompt bodies, no response bodies, no credentials. |
| `.kgmd/build.lock` | any build stage | Exclusive `flock` held for the duration of a build; the file is removed on release. A second build refuses to start while a live process holds it. |

Because everything is in one file, `.kgmd/` is safe to exclude from backups and from version control;
markdown files are the source of truth and the graph is reproducible from them.

`kgmd reset` is the softer option: it clears the graph tables in place and resets each document's
extraction marker so the next build re-extracts, while `kgmd reset --hard` also drops documents and
chunks. Neither clears the `vec_chunks` and `vec_entity_mentions` vector tables, so deleting
`.kgmd/graph.db` and running `kgmd init` again remains the only fully clean slate.

## Vocabulary

Six terms, one table each. Other pages link to these headings rather than restate them.

### document

One markdown file on disk, identified by its path relative to the corpus root. Lives in `documents`,
one row per file, with the file's sha256 `content_hash`, its size, its mtime, and
`last_extracted_hash` — the content hash as of the last successful extraction.

Discovery is a recursive glob for `*.md` under the corpus root, restricted to `corpus.include` when
that key is set, and always excluding any path with a dot-prefixed component, which is what keeps
`.kgmd/`, `.git/` and similar directories out of your graph.

Incrementality is content-based, not time-based. `content_hash` decides whether a file is re-ingested
and `last_extracted_hash` decides whether it is re-extracted; the stored mtime is recorded but is
never consulted for a skip decision. Touching a file changes nothing. Editing one byte re-ingests it,
discards its chunks — which cascades to its mentions — and queues it for extraction.

### chunk

A contiguous span of one document's text, sized for a single LLM call. Lives in `chunks`, with
`chunk_index`, the `content` itself, and `char_start`/`char_end` offsets into the source file, so any
chunk can be traced back to the exact region of markdown it came from.

Splitting is controlled by `chunking.split_on`: `paragraph` (the default) splits on blank lines,
`heading` splits before each ATX heading, and `fixed` cuts fixed-size windows with
`chunking.overlap_chars` of overlap. The paragraph and heading strategies merge consecutive segments
up to `chunking.max_chars` rather than emitting one chunk per paragraph.

Chunks are the unit of extraction and the unit of semantic search: `kgmd find` and the MCP `search`
tool return chunks, not whole documents.

### entity

A thing the graph knows about, deduplicated across the whole corpus. Lives in `entities`, keyed
uniquely by `(canonical_name, entity_type)`, with a free-form JSON `attributes` object. Both the type
vocabulary and the attribute keys are chosen by the LLM during extraction; kgmd imposes no fixed
ontology.

`canonical_name` is the one name the graph uses for the thing. Extraction sets it from the surface
form it saw; resolution may rewrite it when it merges duplicates. Query commands match canonical names
exactly — `kgmd entity` and the MCP entity tools take the canonical name, and `--type` disambiguates
when the same name exists under two types.

### mention

One occurrence of an entity in one chunk. Lives in `entity_mentions`, linking an `entity_id` to a
`chunk_id`, and recording the `surface_form` as it actually appeared, optional character offsets, the
`extraction_run_id` that produced it, and a `confidence`.

Mentions are what make the graph auditable: every entity can be traced to the passages that produced
it, which is what `kgmd entity` shows. They are also the input to resolution — it is mention surface
forms, not canonical names, that get embedded into `vec_entity_mentions` and clustered. Merging an
entity re-points its mentions to the survivor, so nothing is lost when two entities turn out to be
one.

### relation

A directed, typed edge between two entities: subject, predicate, object. Lives in `relations`, with an
`evidence_chunk_id` pointing at the chunk that stated it, the `extraction_run_id`, a `confidence`, and
JSON `attributes`. Predicates are strings the LLM chose, not a closed set.

Uniqueness is over `(subject_id, predicate, object_id, evidence_chunk_id)`, so the same fact asserted
by two different chunks is stored twice, once per piece of evidence. Direction is preserved on
storage, but traversal ignores it: `kgmd neighbors` and `kgmd path` walk the graph undirected, which
is why a path may report a hop whose stored direction is the reverse of the way you are reading it.

### induced schema

A description of the graph that was derived from the graph, after the fact. Lives in
`schema_versions` as a YAML document with `entity_types` and `relation_types` sections, alongside the
LLM model that produced it, its creation timestamp, and the two type counts. The `current_schema` view
selects the newest row, which is what `kgmd schema` and the MCP schema tool read.

It is documentation, not validation. Nothing in the pipeline consults the schema when extracting or
resolving, and no extraction is rejected for disagreeing with it. `induction.hierarchy_depth` bounds
how deeply the LLM may nest entity types. Each `kgmd induce` run appends a new version rather than
overwriting the previous one, so schema drift over the life of a corpus stays visible.

## Why the stages are separate

The two reasons are recovery and cost, and both come from the same fact: extract is the expensive
stage and induce is the cheap one.

Extraction spends one LLM call per chunk. Resolution spends one call per ambiguous cluster. Induction
spends one call, or two if it has to be corrected. So when induction produces a schema you dislike,
re-running `kgmd induce` costs one call — re-running the whole build would cost hundreds. The same
logic applies after tuning `resolution.similarity_threshold`: `kgmd resolve` re-clusters from the
mentions already in the database without touching extraction.

Recovery works the same way. If a build dies mid-extraction, the documents that finished are already
marked with their `last_extracted_hash` and committed; the next run picks up only the rest. Partial
failure inside extraction is tolerated too — chunks whose LLM call failed after its retries are
skipped rather than aborting the run, and any document with no successful chunk stays unmarked and is
retried next time.

The tuning loop that falls out of this: build once, inspect, then re-run the single stage whose
configuration you changed. [./guides/maintenance.md](./guides/maintenance.md) covers which stage to
re-run after which kind of edit, and [./reference/configuration.md](./reference/configuration.md)
documents the keys each stage reads.

## Prompts are yours

All three LLM stages load their prompt from a plain text file, and each prefers a per-corpus override
over the copy bundled in the installed package. Drop a file into `.kgmd/prompts/` — the directory
`kgmd init` creates empty — and that stage uses it.

| Override file | Stage | Placeholders the template must keep |
|---|---|---|
| `.kgmd/prompts/extract.txt` | extract | `{entity_types}`, `{relation_predicates}` |
| `.kgmd/prompts/resolve.txt` | resolve | `{entity_type}`, `{cluster_details}` |
| `.kgmd/prompts/induce.txt` | induce | `{entity_stats}`, `{relation_stats}`, `{hierarchy_depth}`, `{timestamp}` |

The bundled originals live in the installed package at `kgmd/prompts/` under the same three names;
copy one out and edit it rather than writing from scratch. Each template is formatted with exactly the
placeholders listed above, so removing one is fine but introducing an unknown `{name}` breaks the
stage.

Two caveats. Extraction and resolution parse the model's reply as JSON against a fixed shape — an
entity needs a surface form and a type, a relation needs subject, predicate and object, and a
resolution reply needs partitions of member surface forms — so an override that changes the requested
output shape will fail parsing. And `kgmd resolve` and `kgmd induce` honour their overrides while the
same stages run from `kgmd build` do not, so verify a new resolve or induce prompt by running that
command directly.
