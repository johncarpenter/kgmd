# CLI Reference
> Applies to kgmd 0.1.x

This page is the complete reference for the `kgmd` command-line interface: every command, every
parameter, every default, and what each command actually touches on disk. Read it when you need the
exact spelling of a flag, want to know whether a command calls a language model or only reads the
local database, or are scripting kgmd and need the machine-readable output form. For the meaning of
the words *document*, *chunk*, *entity*, *mention*, *relation*, and *induced schema*, see
[../concepts.md](../concepts.md). For the settings that change how these commands behave, see
[./configuration.md](./configuration.md).

## Global options

`--debug` is the only option on the `kgmd` group itself. It goes before the subcommand:

```bash
kgmd --debug build
```

Without it, kgmd installs an exception hook that renders an unhandled exception as a single
`Error: <message>` line on stderr and exits with status 1, so a failing build does not bury the
message under a stack trace. With `--debug` the hook is not installed and the exception propagates,
so Python prints the full traceback — that is what to attach to a bug report. Usage mistakes and
explicitly raised command errors (for example a missing corpus) are always reported as a one-line
message regardless of `--debug`; the flag only changes how *unexpected* exceptions are rendered.

Every command also accepts `--help`, which prints its usage and exits.

Two groups of commands differ in what they need:

- **Needs a provider credential**: `build`, `extract`, `resolve`, `induce`. These call a language
  model through litellm, which reads the credential implicitly from the environment (for example
  `OPENROUTER_API_KEY` for the default `openrouter/...` model). kgmd never reads, prompts for,
  stores, or logs the credential itself.
- **Purely local reads**: `stats`, `entities`, `relations`, `entity`, `neighbors`, `path`, `schema`,
  `export`. These only open `.kgmd/graph.db` and need no network access.

`find` is a third case: it needs no LLM credential, but it embeds your query, so it loads the
embedding model. With the default local `fastembed` backend the first run downloads model weights.

`init`, `reset`, and `mcp` need neither an LLM nor an embedding model at startup.

## Commands

### init

Initialize a new kgmd corpus.

**Usage**: `kgmd init [OPTIONS]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--path` | path | `.` | Directory to initialize. |
| `--help` | flag | off | Show usage and exit. |

Creates `.kgmd/` inside the target directory containing `logs/`, `prompts/`, a `config.yaml`
written from the built-in defaults, and an initialized `graph.db`. It also writes a starter
`.kgmdignore` at the target directory itself — beside your markdown, not inside `.kgmd/` — whose
every line is a comment, so it documents the syntax without excluding anything. An existing
`.kgmdignore` is never overwritten. It then prints the resolved corpus directory, database path,
config path, and ignore-file path.

If `.kgmd/` already exists the command is a no-op: it prints `Already initialized at <path>`,
echoes the existing `config.yaml` if there is one, and changes nothing — including leaving a missing
`.kgmdignore` missing. Re-running `kgmd init` is therefore safe and is a quick way to view the
corpus config. To add an ignore file to an existing corpus, write one by hand; see
[./configuration.md](./configuration.md).

```bash
cd ~/notes
kgmd init
```

```bash
kgmd init --path ~/notes/research
```

### stats

Show corpus statistics.

**Usage**: `kgmd stats [OPTIONS]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--db` | path | `<corpus>/.kgmd/graph.db` | Alternate database path. |
| `--json` | flag | off | Emit a JSON object instead of tables. |
| `--help` | flag | off | Show usage and exit. |

Without `--db` the database is located by walking up from the working directory for a `.kgmd/`
directory. If no corpus is found the command fails with
`No .kgmd directory found. Run 'kgmd init' first.`; if the resolved path has no database file it
fails with `Database not found: <path>`.

Human output is a `Corpus Statistics` table of document, chunk, entity, and relation counts,
followed by an `Entities by Type` table and a `Relations by Predicate` table when those breakdowns
are non-empty, followed by one dim line each for the last extraction run and the last resolution
run (timestamp, status, and documents processed or merges).

```bash
kgmd stats
```

**Structured output**:

```bash
kgmd stats --json
```

The JSON object carries `documents`, `chunks`, `entities`, `relations`, the `entity_types` and
`relation_predicates` count maps, and `last_extraction` / `last_resolution` (each `null` if the
stage has never run). `--json` is the supported form for scripting; the tables are for humans and
their layout is not a stable interface.

### build

Build the knowledge graph: extract, resolve, induce.

**Usage**: `kgmd build [OPTIONS] [PATH]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `PATH` | argument | `.` | Corpus directory; must exist. |
| `--db` | path | `<PATH>/.kgmd/graph.db` | Alternate database path. |
| `--config` | path | — | **Accepted but ignored.** See the warning below. |
| `--dry-run` | flag | off | Report the files that would be indexed, then exit without building. |
| `--json` | flag | off | Output as JSON. Requires `--dry-run`. |
| `--help` | flag | off | Show usage and exit. |

> `--config` is parsed and then discarded: `build` always loads the corpus directory's own
> `.kgmd/config.yaml`. Passing a different file has no effect, and no warning is printed. To change
> build settings, edit the corpus config. See
> [the configuration reference](./configuration.md).

This is the whole pipeline and the command you normally run. It fails with
`Not a kgmd corpus (no .kgmd/ in <path>). Run 'kgmd init' first.` if `PATH` has no `.kgmd/`
directory, then takes the exclusive build lock at `.kgmd/build.lock` and runs six stages, printing
a heading and a one-line summary for each:

1. **Ingesting documents** — scan markdown, chunk it, report new / updated / skipped / chunks
   created, plus a `Removed:` line when documents that are no longer in the corpus were dropped from
   the graph.
2. **Embedding chunks** — verify the corpus embedding model, then embed chunks that have no vector.
3. **Extracting entities and relations** — report documents processed, entities created, relations
   created.
4. **Embedding entity mentions** — embed mentions that have no vector.
5. **Resolving entities** — report merges.
6. **Inducing schema** — report entity type and relation type counts.

It ends with `Build complete.` Stages 1, 2, and 4 skip work whose content hash is unchanged, so a
second `kgmd build` over an unmodified corpus is cheap. Stages 3, 5, and 6 are the LLM stages.

`extract`, `resolve`, and `induce` exist as separate commands so you can re-run a single stage
after a partial failure instead of repeating the whole pipeline — for example when extraction
succeeded but induction hit a provider timeout.

`--dry-run` answers "what would this cost" before it costs anything. It resolves the file set —
`corpus.include` scoping, then `.kgmdignore`, then the dot-path rule — prints the paths that would be
indexed with counts of what each stage excluded, and exits. It takes no build lock, makes no provider
call, writes nothing, and does not even create `graph.db` for a corpus that has never been built. It
also reports how many already-indexed documents would be **removed** because their path is no longer
in the corpus. This is the way to check `.kgmdignore` patterns; see
[./configuration.md](./configuration.md) for the syntax.

`--json` prints that same report as a single JSON object and nothing else. It requires `--dry-run`
and fails with `--json requires --dry-run.` on its own, because a `--json` that silently implied
`--dry-run` would mean `kgmd build --json` quietly not building.

**Structured output**: with `--dry-run --json`, one object with `included`, `ignored`, and `dotpath`
arrays of corpus-relative paths, and a `counts` object holding `included`, `ignored`, `dotpath`, and
`would_remove`. Paths are sorted and always relative to the corpus root, matching the form stored in
`documents.path`.

```bash
kgmd build --dry-run
```

```bash
kgmd build --dry-run --json
```

```bash
kgmd build
```

```bash
kgmd build ~/notes --config ~/notes/alt-config.yaml
```

### extract

Extract entities and relations from documents.

**Usage**: `kgmd extract [OPTIONS] [PATH]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `PATH` | argument | `.` | Corpus directory; must exist. |
| `--db` | path | `<PATH>/.kgmd/graph.db` | Alternate database path. |
| `--force` | flag | off | Re-extract all documents, even unchanged ones. |
| `--help` | flag | off | Show usage and exit. |

Stage 3 of `build`, plus the ingest and embed steps it depends on. Under the build lock it ingests
documents, embeds new chunks, extracts, then embeds new mentions, and prints `Extraction complete.`
It does **not** resolve duplicates or induce a schema. Because it ingests, it also drops documents
that are no longer part of the corpus — deleted, renamed, or newly excluded by `.kgmdignore` —
exactly as `build` does.

By default a document is re-extracted only when its content hash differs from the hash recorded at
its last extraction, so unchanged files cost nothing. `--force` ignores that check and re-extracts
every document — use it after editing a prompt template in `.kgmd/prompts/` or changing
`llm.model`, since neither changes a document's content hash.

```bash
kgmd extract
```

```bash
kgmd extract --force
```

### resolve

Resolve duplicate entities.

**Usage**: `kgmd resolve [OPTIONS] [PATH]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `PATH` | argument | `.` | Corpus directory; must exist. |
| `--db` | path | `<PATH>/.kgmd/graph.db` | Alternate database path. |
| `--help` | flag | off | Show usage and exit. |

Stage 5 of `build`, run on its own. Under the build lock it clusters mentions whose embeddings are
closer than `resolution.similarity_threshold`, verifies each candidate cluster with the LLM when
`resolution.llm_verify_clusters` is enabled, merges the confirmed duplicates, prints the merge
count, then `Resolution complete.`

Resolution reads mention embeddings, so it is only useful after extraction has produced mentions.
Tune its behaviour through `resolution.similarity_threshold`, `resolution.llm_verify_clusters`, and
`resolution.max_cluster_size` — see [./configuration.md](./configuration.md).

```bash
kgmd resolve
```

### induce

Induce schema from the knowledge graph.

**Usage**: `kgmd induce [OPTIONS] [PATH]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `PATH` | argument | `.` | Corpus directory; must exist. |
| `--db` | path | `<PATH>/.kgmd/graph.db` | Alternate database path. |
| `--help` | flag | off | Show usage and exit. |

Stage 6 of `build`, run on its own. Under the build lock it asks the LLM to generalize the observed
entity types and predicates into a typed schema, stores it as a new schema version, prints the
entity type and relation type counts, then `Induction complete.` Run it after adding documents when
you only want the schema refreshed. Read the result back with `kgmd schema`.

```bash
kgmd induce
```

### find

Semantic search over chunks.

**Usage**: `kgmd find [OPTIONS] QUERY`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `QUERY` | argument | required | Natural-language search text. |
| `--limit` / `-n` | int | `10` | Number of results. |
| `--db` | path | `<corpus>/.kgmd/graph.db` | Alternate database path. |
| `--json` | flag | off | Emit the raw result list as JSON. |
| `--help` | flag | off | Show usage and exit. |

`find` embeds `QUERY` and ranks chunks by vector distance, so unlike the other read commands it
loads the embedding model configured for the corpus. With the default local `fastembed` backend
that means a one-off model download on first use and a second or two of load time on every
subsequent run; no credential is needed. The corpus is always located by walking up for `.kgmd/`,
because the embedding configuration is read from the corpus config even when `--db` points
elsewhere.

Human output is one block per hit: rank, document path, vector distance to four decimal places, the
first 300 characters of the chunk on one line, and the entities mentioned in that chunk. When
nothing matches it prints `No results found.`

```bash
kgmd find "who owns the billing service" -n 5
```

**Structured output**:

```bash
kgmd find "who owns the billing service" --limit 5 --json
```

Each JSON element carries `document_path`, `chunk_text` (untruncated), `distance`, and an `entities`
list of `name`/`type` pairs. `--json` is the supported form for scripting.

### entities

List entities.

**Usage**: `kgmd entities [OPTIONS]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--type` | string | all types | Filter by entity type. |
| `--limit` / `-n` | int | `50` | Maximum rows returned. |
| `--search` | string | no filter | Substring search on name. |
| `--db` | path | `<corpus>/.kgmd/graph.db` | Alternate database path. |
| `--json` | flag | off | Emit the raw result list as JSON. |
| `--help` | flag | off | Show usage and exit. |

`--type` matches the entity type exactly; `--search` is a substring match on the name. Both may be
combined. Human output is an `Entities` table with Name, Type, and Attributes columns, where
Attributes is the entity's attribute object rendered as compact JSON, or empty when it has none.
With no matches it prints `No entities found.`

```bash
kgmd entities --type Person -n 20
```

```bash
kgmd entities --search "Acme"
```

**Structured output**:

```bash
kgmd entities --type Person --json
```

Each JSON element carries `name`, `type`, and `attributes`. `--json` is the supported form for
scripting.

### relations

List relations.

**Usage**: `kgmd relations [OPTIONS]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--predicate` | string | all predicates | Filter by predicate. |
| `--subject` | string | any subject | Filter by subject entity name. |
| `--object` | string | any object | Filter by object entity name. |
| `--limit` / `-n` | int | `50` | Maximum rows returned. |
| `--db` | path | `<corpus>/.kgmd/graph.db` | Alternate database path. |
| `--json` | flag | off | Emit the raw result list as JSON. |
| `--help` | flag | off | Show usage and exit. |

Filters combine, so `--subject` plus `--predicate` narrows to one entity's edges of one kind. Human
output is a `Relations` table with Subject, Predicate, Object, and Confidence columns; Confidence is
formatted to two decimal places and left blank when the relation has none. With no matches it
prints `No relations found.`

```bash
kgmd relations --predicate works_at -n 100
```

```bash
kgmd relations --subject "Sarah Chen"
```

**Structured output**:

```bash
kgmd relations --predicate works_at --json
```

Each JSON element carries `subject`, `predicate`, `object`, and `confidence`. `--json` is the
supported form for scripting.

### entity

Show full record for a single entity.

**Usage**: `kgmd entity [OPTIONS] NAME`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `NAME` | argument | required | Entity name to look up. |
| `--type` | string | any type | Disambiguate by entity type. |
| `--db` | path | `<corpus>/.kgmd/graph.db` | Alternate database path. |
| `--json` | flag | off | Emit the raw record as JSON. |
| `--help` | flag | off | Show usage and exit. |

Use `--type` when the same name exists under more than one type. If nothing matches, the command
fails with `Entity '<name>' not found.` — this is an error, not an empty result, so it is safe to
use in a script's exit-status check.

Human output is the name with its type, the attribute object as JSON when present, then up to the
first ten mentions as `"surface form" in <document>`, then outgoing relations rendered
`→ predicate → object (type)` and incoming relations rendered `← predicate ← subject (type)`. Note
that the human view caps the mention list at ten; `--json` does not.

```bash
kgmd entity "Brian Anderson"
```

```bash
kgmd entity "Acme" --type Organization
```

**Structured output**:

```bash
kgmd entity "Brian Anderson" --json
```

The JSON record carries `id`, `name`, `type`, `attributes`, the complete `mentions` list (each with
`surface_form`, `confidence`, `document`, and a truncated `chunk_text`), and the
`outgoing_relations` and `incoming_relations` lists. `--json` is the supported form for scripting.

### neighbors

Subgraph traversal around an entity.

**Usage**: `kgmd neighbors [OPTIONS] NAME`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `NAME` | argument | required | Entity to traverse from. |
| `--depth` / `-d` | int | `1` | Traversal depth in hops. |
| `--type` | string | all types | Restrict the subgraph to one entity type. |
| `--db` | path | `<corpus>/.kgmd/graph.db` | Alternate database path. |
| `--json` | flag | off | Emit the raw subgraph as JSON. |
| `--help` | flag | off | Show usage and exit. |

Returns the nodes and edges reachable from `NAME` within `--depth` hops. Depth 1 is the immediate
neighbourhood; each extra hop grows the result quickly on a dense graph, so raise it deliberately.
Human output prints `Neighbors of <name> (depth=<n>):`, then the node list as `name (type)`, then
the edge list as `source → predicate → target`. An unknown name is not an error here: it prints
`Entity '<name>' not found or has no neighbors.` and exits successfully.

```bash
kgmd neighbors "Brian Anderson" --depth 2
```

**Structured output**:

```bash
kgmd neighbors "Brian Anderson" -d 2 --json
```

The JSON object carries a `nodes` list and an `edges` list; an unknown name yields both as empty
arrays rather than an error. `--json` is the supported form for scripting.

### path

Find shortest path between two entities.

**Usage**: `kgmd path [OPTIONS] FROM_NAME TO_NAME`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `FROM_NAME` | argument | required | Start entity name. |
| `TO_NAME` | argument | required | Destination entity name. |
| `--max-depth` | int | `5` | Maximum hops to search before giving up. |
| `--db` | path | `<corpus>/.kgmd/graph.db` | Alternate database path. |
| `--json` | flag | off | Emit the raw edge list as JSON. |
| `--help` | flag | off | Show usage and exit. |

Both names are positional and order matters: the search runs from `FROM_NAME` to `TO_NAME`. Human
output prints `Path: <from> → <to>` and then one line per edge as `source → predicate → target`.
When no path exists within `--max-depth` it prints
`No path found between '<from>' and '<to>'.` and exits successfully.

```bash
kgmd path "Sarah Chen" "Acme Corp" --max-depth 4
```

**Structured output**:

```bash
kgmd path "Sarah Chen" "Acme Corp" --json
```

The JSON value is the ordered list of edges, each with `source`, `predicate`, and `target`, or
`null` when no path was found. `--json` is the supported form for scripting.

### schema

Show the current induced schema.

**Usage**: `kgmd schema [OPTIONS]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--db` | path | `<corpus>/.kgmd/graph.db` | Alternate database path. |
| `--json` | flag | off | Emit the raw schema record as JSON. |
| `--help` | flag | off | Show usage and exit. |

Prints the most recent schema version. Human output is a header line with the schema version id and
its creation timestamp, the LLM model that produced it, the entity type and relation type counts,
and then the schema itself as YAML. If induction has never run it prints
`No schema has been induced yet. Run 'kgmd build' or 'kgmd induce'.` and exits successfully.

```bash
kgmd schema
```

**Structured output**:

```bash
kgmd schema --json
```

The JSON record carries `id`, `created_at`, `llm_model`, `entity_type_count`,
`relation_type_count`, and the nested `schema` object. Note that the human form renders `schema` as
YAML while `--json` returns it as JSON. `--json` is the supported form for scripting.

### export

Export the knowledge graph.

**Usage**: `kgmd export [OPTIONS]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--format` | choice | **required** | One of `jsonld`, `cypher`, `graphml`. |
| `--output` / `-o` | path | stdout | Output file path. Stdout if omitted. |
| `--db` | path | `<corpus>/.kgmd/graph.db` | Alternate database path. |
| `--help` | flag | off | Show usage and exit. |

`--format` has no default and is required; omitting it is a usage error, and any value outside the
three choices is rejected by the parser before the database is opened. Without `--output` the whole
serialization is written to stdout, so it can be piped. With `--output` the content is written to
that path and the command prints `Exported to <path>` instead. Format details and consuming tools
are in [./export.md](./export.md).

```bash
kgmd export --format jsonld -o graph.jsonld
```

```bash
kgmd export --format cypher | wc -l
```

### reset

Reset the knowledge graph, keeping config and prompts.

**Usage**: `kgmd reset [OPTIONS]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--hard` | flag | off | Also remove documents and chunks. |
| `--yes` | flag | off | Confirm without prompting. |
| `--help` | flag | off | Show usage and exit. |

`reset` is destructive, so it prompts `This will delete all graph data. Continue?` before doing
anything; answering no aborts without touching the database. `--yes` skips the prompt and is what
you want in a script. There is no `--db` option: `reset` always locates the corpus by walking up for
`.kgmd/` and operates on `<corpus>/.kgmd/graph.db`, failing with `Database not found: <path>` if
that file is absent.

Under the build lock, both modes delete relations, entity mentions, entities, schema versions, and
the extraction and resolution run history; clear each document's recorded last-extracted hash;
`VACUUM` the database; and truncate `.kgmd/logs/build.log`. Config and prompt templates under
`.kgmd/` are never touched.

The two modes differ in what survives:

- **Default** — document and chunk rows, and their embeddings, are kept. The next `kgmd build` sees
  unchanged content hashes during ingest, so it re-chunks and re-embeds nothing; because the
  last-extracted hash was cleared, extraction still reruns over every document. It prints
  `Reset complete.` and tells you to run `kgmd build`.
- **`--hard`** — chunks and documents are deleted too, so the next build re-ingests, re-chunks, and
  re-embeds the corpus from scratch. It prints `Full reset complete.`

Use the default when you want to re-extract with a new prompt or model but keep the embedding work.
Use `--hard` when the ingest or chunking configuration changed. To discard a corpus entirely,
delete `.kgmd/graph.db`; that is also the documented fix for changing the embedding model, which is
fixed at corpus creation — see [../guides/troubleshooting.md](../guides/troubleshooting.md).

```bash
kgmd reset --yes
```

```bash
kgmd reset --hard --yes
```

### mcp

Launch MCP server over stdio.

**Usage**: `kgmd mcp`

| Parameter | Type | Default | Description |
|---|---|---|---|
| none | — | — | This command takes no arguments or options. |
| `--help` | flag | off | Show usage and exit. |

Starts the Model Context Protocol server on stdin/stdout and blocks until the client disconnects.
It is meant to be launched by an MCP client, not run interactively — a bare invocation in a
terminal looks like it has hung, because it is waiting for protocol frames.

The server takes no `--db` option: it resolves its database from the process working directory as
`.kgmd/graph.db`, so the client's configured working directory decides which corpus is served. The
seven registered tools and a copy-pasteable client configuration are in
[../guides/mcp.md](../guides/mcp.md).

```bash
kgmd mcp
```
