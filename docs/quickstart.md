# Quickstart
> Applies to kgmd 0.1.x

For a reader who has kgmd installed and wants a working graph, not a tour. Follow this page in order
and in about ten minutes you will have a queryable knowledge graph over a directory of markdown
notes and will have run six kinds of query against it.

## Before you start

- kgmd installed and `kgmd --help` working — see [Install](./install.md).
- A provider credential exported in the shell you are about to use:

  ```bash
  export OPENROUTER_API_KEY="sk-..."
  ```

  kgmd passes the configured model id to litellm, which picks the credential up from the
  environment. Nothing is stored on disk.
- Network access. The build calls your provider, and the first build also downloads the local
  fastembed embedding model.

## Choose a corpus

A corpus is a directory of `.md` files. kgmd walks it recursively and skips dotted directories, so a
notes folder inside a git repository works untouched.

### Your own notes

Any directory of markdown will do. Point the rest of this page at it:

```bash
cd ~/notes
```

Start with a small subdirectory the first time. Cost and wall-clock time scale with the amount of
text, and you want to see the shape of the output before committing a large corpus.

### No notes handy

This creates a two-note corpus with an obvious relation between a person and a company, so
extraction has something to find. It needs no git checkout and no download:

```bash
mkdir -p ~/kgmd-demo && cd ~/kgmd-demo

cat > dana-okoye.md <<'EOF'
## Dana Okoye

Dana Okoye is the head of platform engineering at Meridian Freight. She joined in 2021 and now
leads the team that builds Railyard, the shipment-tracking service used by Meridian's dispatchers.

Before Meridian Freight she spent six years on infrastructure at a logistics startup.
EOF

cat > meridian-freight.md <<'EOF'
## Meridian Freight

Meridian Freight is a regional logistics company operating out of Toronto. Its platform
engineering group, led by Dana Okoye, maintains Railyard, the shipment-tracking service that
every dispatcher uses.

Meridian Freight partners with Northbank Logistics on cross-border routes.
EOF
```

The repository's `tests/fixtures/` notes — seven interlinked files about people, a company, and its
technology choices — are the corpus behind the worked example in
[Personal notes](./examples/personal-notes.md). They are not shipped in the wheel, so that path
requires a git checkout of kgmd. The two notes above require nothing.

## Build the graph

Initialize the corpus. This creates `.kgmd/` with a config file, a prompts directory, a logs
directory, and an empty SQLite database:

```bash
kgmd init
```

```text
Initialized kgmd corpus at ~/kgmd-demo
  Database: ~/kgmd-demo/.kgmd/graph.db
  Config:   ~/kgmd-demo/.kgmd/config.yaml
```

### Cost notice

The next command sends the text of your notes to your LLM provider. **`kgmd build` costs money and
takes time, both roughly proportional to corpus size.** Each note is split into chunks of up to
4,000 characters and every chunk becomes at least one provider call — more when a malformed
response is retried — while duplicate-entity verification and schema induction add a handful on
top. For the two small notes above that is a few calls and well under a minute of provider work:
negligible spend on any mainstream model. For a few hundred notes it is hundreds of calls, so read
[Maintenance](./guides/maintenance.md) first. Nothing is charged for embeddings; those run locally.

Then build:

```bash
kgmd build
```

The command runs six numbered stages and prints a bold heading plus a one-line summary for each:

1. **Ingesting documents** — walks the corpus, hashes each file, and reports new, updated, skipped,
   and chunks created.
2. **Embedding chunks** — local fastembed pass; reports how many new chunks were embedded. On a cold
   machine this is where the embedding model downloads.
3. **Extracting entities and relations** — the expensive stage. A `rich` progress bar labelled
   `Extracting` advances once per chunk, with up to four provider calls in flight at a time; the
   summary line reports documents processed, entities created, and relations created.
4. **Embedding entity mentions** — local again; reports mentions embedded.
5. **Resolving entities** — clusters near-identical mentions, asks the model to confirm the
   candidates, and reports how many merges it made.
6. **Inducing schema** — reports the number of entity types and relation types in the induced
   schema.

It finishes with `Build complete.` A failure in a stage stops the build with a one-line `Error:`;
re-run with `kgmd --debug build` for the traceback. Only one build can run against a corpus at a
time: a second concurrent build does not queue, it fails immediately naming the process that holds
the lock.

## Query it

Run these from inside the corpus directory; kgmd finds `.kgmd/` by walking up from your working
directory. Extraction is a model's judgement call, so on the two-note corpus expect the shapes
below, not specific numbers.

What got built:

```bash
kgmd stats
```

A `Corpus Statistics` table with Documents, Chunks, Entities, and Relations, followed by an
`Entities by Type` table and a `Relations by Predicate` table, then dim lines summarising the last
extraction and resolution runs. On the demo corpus expect two documents, a small number of chunks,
and a handful of entities — a person, a company or two, and a service.

Everything the extractor found:

```bash
kgmd entities
```

An `Entities` table with three columns: Name, Type, and Attributes (a JSON blob, empty when the
model returned none). The type labels are the model's own, so take them from this table or from
`kgmd stats`; then narrow with `--type` or match part of a name with `--search okoye`.

Which chunks are about a topic, by meaning rather than keyword:

```bash
kgmd find "shipment tracking"
```

A numbered list of matching chunks, each showing the source document path, a distance score where
lower is closer, the first 300 characters of the chunk, and the entities linked to it. This is the
local embedding index, so it costs nothing to run.

Everything known about one entity:

```bash
kgmd entity "Dana Okoye"
```

The name and type, any attributes, up to ten mentions with their surface form and source document,
then outgoing and incoming relations. If the name does not match, the command exits with
`Error: Entity '...' not found.` — run `kgmd entities` and copy the name exactly as extracted.

The neighbourhood around an entity, two hops out:

```bash
kgmd neighbors "Dana Okoye" --depth 2
```

A node list and an edge list, each edge printed as subject → predicate → object. Depth 1 is direct
relations only; depth 2 picks up the company's other connections.

How two entities are connected:

```bash
kgmd path "Dana Okoye" "Northbank Logistics"
```

The shortest chain of relations between them, one edge per line, or a dim `No path found` line when
the graph has no route within the depth limit (five hops by default).

Eight commands also take `--json`, which prints the same data as parseable JSON instead of a table:

```bash
kgmd stats --json
```

Full option lists, structured-output shapes, and the remaining commands are in the
[CLI reference](./reference/cli.md).

## Expose it to an assistant

`kgmd mcp` serves the same read-only queries over stdio as seven MCP tools, so an assistant can
search chunks, look up entities, traverse neighbours, find paths, list relations, and read the
induced schema without you typing commands. The server resolves its database from the working
directory it is launched in, which makes the client's `cwd` setting load-bearing. Registered tool
names and copy-pasteable client configuration are in [MCP integration](./guides/mcp.md).

## Re-running

Re-run `kgmd build` whenever the notes change. Ingest compares a sha256 hash of each file's content
against the stored hash and skips unchanged files, and extraction is gated by a second hash recorded
at extraction time, so an unchanged corpus costs nothing but a few local hashes. Editing one note
re-chunks and re-extracts that note alone. Modification times are stored but never used to decide
what to skip. [Maintenance](./guides/maintenance.md) covers forced re-extraction, resets, backups,
and the build lock.

## Where to go next

- [Concepts](./concepts.md) — what document, chunk, entity, mention, relation, and induced schema
  mean in kgmd's output.
- [CLI reference](./reference/cli.md) — every command, every option, every structured-output form.
- [Personal notes](./examples/personal-notes.md) — the same journey over the repository's fixture
  corpus, with pinned expected output.
