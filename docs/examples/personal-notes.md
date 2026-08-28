# Walkthrough: A Searchable Graph Over Your Own Notes
> Applies to kgmd 0.1.x

For anyone with a directory of markdown notes — a Zettelkasten, meeting notes, a research journal —
who wants to query it instead of grepping it. By the end you will have a graph built from your own
files and a query session you can repeat: semantic search over passages, entity records with every
alias attached, neighbourhood traversal, and shortest paths between two things you wrote about
months apart.

## Goal

Turn an existing folder of markdown into a knowledge graph stored beside it in `.kgmd/graph.db`,
then answer questions about it from the command line. Three kinds of question are in scope:

- "Which passages talk about X?" — semantic search over chunks (`kgmd find`).
- "What do I know about this person or project?" — a single entity record with its mentions and
  relations (`kgmd entity`).
- "How are these two things connected?" — traversal and path finding (`kgmd neighbors`,
  `kgmd path`).

## Prerequisites

- kgmd 0.1.0 installed and on `PATH`. See [install.md](../install.md).
- A provider credential for the LLM stages, exported in the environment before you build. kgmd never
  reads, prompts for, stores, or logs credentials — `litellm` picks the variable up implicitly from
  the model id you configured:

  ```bash
  export OPENROUTER_API_KEY="sk-..."
  ```

- No embedding credential. The default `embedding.backend` is `fastembed`, which runs
  `BAAI/bge-small-en-v1.5` locally (384 dimensions). The model is downloaded on first use.
- **A git checkout is required only if you want the reproducible stand-in corpus.** Working on your
  own notes needs no checkout — the wheel is enough. The sample notes under `tests/fixtures/` are
  test fixtures and are not shipped in the published wheel, so reaching them means cloning the
  repository.

## Corpus

Use your own notes directory. Any layout works: kgmd walks the tree, takes every `*.md`, and always
skips path components beginning with a dot (so `.kgmd/`, `.git/`, and `.claude/` are never
ingested). A `.kgmdignore` file at the root of the notes directory subtracts further paths from
that walk; step 2 covers it.

If you want a corpus that behaves the same on someone else's machine, use the seven fixture notes in
a git checkout — they are small, densely cross-referential, and deliberately inconsistent about
names, which is what makes the resolution step visible:

```text
tests/fixtures/acme_corp.md
tests/fixtures/brian_anderson.md
tests/fixtures/digital_transformation.md
tests/fixtures/partnerships.md
tests/fixtures/quarterly_review.md
tests/fixtures/sarah_chen.md
tests/fixtures/tech_stack.md
```

Copy that directory somewhere writable and treat the copy as the corpus, or run `kgmd init` inside
the checkout's fixtures directory. A two-note version of the same exercise is in
[quickstart.md](../quickstart.md).

## Steps

### 1. Initialize the corpus

```bash
cd ~/notes
kgmd init
```

`kgmd init` creates `.kgmd/` next to your notes containing `config.yaml` (the full default
configuration, written out key by key), an empty `graph.db`, and empty `logs/` and `prompts/`
directories. It also writes a starter `.kgmdignore` — beside the notes, not inside `.kgmd/` — with
every line commented out, so a fresh corpus indexes exactly what it would have without the file. It
prints the corpus, database, and config paths. Run again in an initialized directory and it prints
the existing config instead of overwriting anything, and leaves an existing `.kgmdignore` untouched.

### 2. Scope and chunk the corpus (optional)

Edit `.kgmd/config.yaml` if the defaults do not fit your notes. Two settings matter most for a
personal corpus:

```yaml
corpus:
  include:
    - journal
    - projects/atlas.md
chunking:
  max_chars: 1500
  split_on: heading
```

- `corpus.include` is a list of **corpus-relative directory or file paths**, not glob patterns. A
  directory entry is searched recursively; a file entry must end in `.md`. Unset (the default) means
  the whole tree.
- `chunking.max_chars` is the binding constraint on chunk size. `split_on` only decides where a
  boundary is *allowed* — `paragraph` (blank lines), `heading` (any `##`-style heading), or `fixed`
  (fixed windows with `chunking.overlap_chars` of overlap). Adjacent segments are merged until
  `max_chars` is reached, so with the default 4000 a short note becomes a single chunk whichever
  `split_on` you choose. Lower `max_chars` if you want finer-grained search hits and more focused
  extraction.

Every key, its default, and its effect is in [configuration.md](../reference/configuration.md).

`corpus.include` only decides which part of the tree is a candidate. To subtract from that
candidate set, write a `.kgmdignore` at the corpus root — gitignore-style patterns, one per line,
`#` for comments:

```text
archive/
drafts/
!archive/2024-decisions.md
```

A personal corpus is where this pays for itself: an `archive/` you never query and a `drafts/` full
of half-finished sentences cost one LLM call per chunk on every build that first touches them.
Patterns are read in order and the last match wins, so the negation above re-admits that one
archived note — which git will not do for a file whose parent directory is excluded. The dot-path
rule is applied last and dominates, so no pattern re-admits `.kgmd/` or `.git/`. Syntax, precedence,
and the constructs that are not supported are in
[configuration.md](../reference/configuration.md).

Check the result before paying for a build:

```bash
kgmd build --dry-run
```

It prints the files that would be indexed, how many the ignore rules and the dot-path rule dropped,
and how many already-indexed documents would be removed. It takes no build lock, makes no provider
call, and creates no database. `--json` gives the same report machine-readably and requires
`--dry-run`.

### 3. Build the graph

```bash
kgmd build
```

The build runs six stages in order and prints a line per stage: ingest (hash, upsert, chunk), embed
chunks, extract entities and relations, embed mentions, resolve duplicates, induce the schema. It
holds an exclusive lock on `.kgmd/build.lock`, so a second build in the same corpus waits rather
than corrupting state.

Extraction is the slow and paid part: one LLM call per chunk, `llm.concurrency` calls in flight
(default 4). Metadata for each call — model, character counts, elapsed time — is appended to
`.kgmd/logs/build.log`; prompt and response bodies are not.

Re-run `kgmd build` after editing notes. Ingest compares a sha256 of the file content against
`documents.content_hash`, and extraction re-runs only where `documents.last_extracted_hash` differs
from the current content hash, so unchanged files cost nothing. File mtime is stored but never used
to decide what to skip. `kgmd extract --force` re-extracts everything regardless.

Removal happens in the same pass, before the insert and update loop. Ingest drops every indexed
document whose path is no longer in the resolved file set — deleted, renamed, and newly excluded by
`.kgmdignore` are one state, not three — together with its chunks, its mentions, the relations whose
evidence came from those chunks, the vectors for both, and any entity the removal leaves with no
mention and no relation. `kgmd build` and `kgmd extract` both do it and both print a `Removed:` line
in the ingest summary when something was removed, and nothing extra when nothing was. If the
resolved set is empty while the graph still holds documents, ingest refuses before writing anything
rather than emptying the graph behind a pattern you did not mean.

### 4. Query the graph

Run these from the corpus directory or any subdirectory — kgmd walks upward looking for `.kgmd/`.

```bash
kgmd stats
kgmd entities --type Person
kgmd entities --search Chen
kgmd find "who designed the data pipeline" -n 5
kgmd entity "Sarah Chen"
kgmd neighbors "Sarah Chen" --depth 2
kgmd path "Sarah Chen" "CFO Centre Canada"
```

Each of these takes `--json` for scripting, and `--db` to point at a database outside the current
corpus. Full parameter lists are in [cli.md](../reference/cli.md).

## Expected output

The samples below are from the seven fixture notes. Only two numbers are deterministic: seven files,
each under 700 characters, give 7 documents and 7 chunks at the default `chunking.max_chars` of
4000. Every entity, relation, and merge count shown is **illustrative of what a typical run
produces** — extraction and LLM-verified resolution vary between runs even at
`llm.temperature: 0.0`, so treat the numbers as shape, not as expected values. Table layouts, column
order, and line formats are exactly what the CLI renders.

`kgmd stats` prints one summary table plus a breakdown table per grouping, then the last extraction
and resolution run:

```text
  Corpus Statistics
┏━━━━━━━━━━━┳━━━━━━━┓
┃ Metric    ┃ Value ┃
┡━━━━━━━━━━━╇━━━━━━━┩
│ Documents │     7 │
│ Chunks    │     7 │
│ Entities  │    24 │
│ Relations │    31 │
└───────────┴───────┘

    Entities by Type
┏━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Type         ┃ Count ┃
┡━━━━━━━━━━━━━━╇━━━━━━━┩
│ Organization │     4 │
│ Person       │     5 │
│ Project      │     2 │
└──────────────┴───────┘

Last extraction: 2026-08-28T12:32:31.392050+00:00 — status: complete, docs: 7
Last resolution: 2026-08-28T12:32:31.392050+00:00 — status: complete, merges: 6
```

`kgmd entities` prints a three-column table — name, type, attributes as compact JSON — sorted by
name, capped by `--limit` (default 50):

```text
                                Entities
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name                   ┃ Type         ┃ Attributes                    ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Acme Corp              │ Organization │ {"industry": "Technology"}    │
│ Brian Anderson         │ Person       │ {"role": "CFO"}               │
│ Digital Transformation │ Project      │                               │
│ Sarah Chen             │ Person       │ {"role": "Software Engineer"} │
└────────────────────────┴──────────────┴───────────────────────────────┘
```

`kgmd find` prints ranked hits: index, document path, vector distance (lower is closer), the first
300 characters of the chunk with newlines flattened, and the entities mentioned in that chunk. With
no hits it prints `No results found.`

`kgmd entity` prints the canonical name and type, attributes, up to ten mentions with their surface
forms and source documents, then outgoing and incoming relations:

```text
Sarah Chen (Person)
  Attributes: {"role": "Software Engineer"}

  Mentions (2):
    - "Dr. Chen" in sarah_chen.md
    - "S. Chen" in quarterly_review.md

  Outgoing relations:
    → works_at → Acme Corp (Organization)
    → designed → Digital Transformation (Project)
```

That mention list is the visible result of resolution. `tests/fixtures/sarah_chen.md` alone writes
"Sarah Chen", "Dr. Chen", and "S. Chen" for the same person, and
`tests/fixtures/quarterly_review.md` adds another "S. Chen"; `tests/fixtures/brian_anderson.md` does
the same with "Brian Anderson", "B. Anderson", and "Anderson". Extraction creates a separate entity
per distinct surface form. Resolution then embeds every mention, clusters mentions of the same
entity type whose cosine similarity exceeds `resolution.similarity_threshold` (0.85), asks the LLM
to confirm the cluster when `resolution.llm_verify_clusters` is true, and merges the confirmed
members: attributes are combined, mentions and relations are re-pointed at the survivor, duplicate
relations are deleted, and the survivor is renamed to the canonical name. One person, many
spellings, one entity record — and `kgmd entity` shows which spelling came from which file.

`kgmd neighbors` runs a breadth-first walk that follows edges in both directions, then prints the
node list and the edge list of the induced subgraph:

```text
Neighbors of Sarah Chen (depth=2):

  Nodes (4):
    - Sarah Chen (Person)
    - Acme Corp (Organization)
    - Digital Transformation (Project)
    - Brian Anderson (Person)

  Edges (3):
    Sarah Chen → works_at → Acme Corp
    Sarah Chen → designed → Digital Transformation
    Brian Anderson → advises → Acme Corp
```

Two things to expect here. Edges are reported in their stored direction, so an edge into the
neighbourhood reads with the outside entity as subject. And `--type` filters entities *discovered
during* the walk, so it can cut a path short: a `Person`-only walk cannot reach a second person
through an intervening organization.

`kgmd path` finds the shortest path treating the graph as undirected, then prints each hop in the
direction the relation is stored — which is why a hop can read "backwards" relative to the direction
of travel:

```text
Path: Sarah Chen → CFO Centre Canada
  Sarah Chen → works_at → Acme Corp
  Brian Anderson → advises → Acme Corp
  Brian Anderson → works_at → CFO Centre Canada
```

Paths longer than `--max-depth` (default 5) are reported as no path found, as are names that are not
canonical entity names — match the name `kgmd entities` shows, or find it first with
`kgmd entities --search`.

## Limitations

- **Extraction quality tracks the model and the prose.** Every entity and relation comes from an LLM
  reading one chunk in isolation, with `llm.model` deciding how well. Notes written as declarative
  statements of fact ("Chen leads the platform team") extract cleanly; allusive or speculative notes
  produce sparse and noisier graphs. Nothing recovers a relation that the text only implies across
  two distant paragraphs.
- **Runs are not reproducible.** `llm.temperature` defaults to `0.0`, but identical input can still
  produce a different entity or relation count on a second build. Treat any count as a description
  of one run.
- **Entities stranded by an earlier forced extraction are not swept.** Removing a note collects the
  entities *that removal* leaves with no mention and no relation, and only those. An entity left
  behind by an earlier `kgmd extract --force` is outside that scope: it stays in the graph and keeps
  appearing in `kgmd entities`. Clearing the graph with `kgmd reset --hard` and rebuilding is the
  way to drop it — see [maintenance.md](../guides/maintenance.md) for what reset does and does not
  touch.
- **Resolution only merges within one entity type.** Mentions clustered as `Person` never merge with
  mentions typed `Organization`, so a mistyped mention stays a separate entity. Raising
  `resolution.similarity_threshold` merges less; lowering it merges more, including things that are
  merely similar.
- **Cost and time scale with chunk count, not corpus size.** Each build spends one LLM call per
  chunk needing extraction, plus one call per candidate duplicate cluster during resolution and one
  for induction. Lowering `chunking.max_chars` improves retrieval precision and increases the number
  of calls proportionally. Incrementality keeps re-builds cheap; the first build over a large corpus
  is not cheap.
- **Large chunks can be truncated.** The extraction stage applies its own local default of 4096
  output tokens, below the `llm.max_tokens` default of 16384, so raising that config key does not
  necessarily raise the extraction limit. Details in
  [configuration.md](../reference/configuration.md).
- **The embedding model is fixed at corpus creation.** Changing `embedding.model` later fails with
  an error telling you to delete `.kgmd/graph.db` and rebuild, because stored vectors are not
  comparable across models.
