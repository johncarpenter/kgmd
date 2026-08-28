# Architecture
> Applies to kgmd 0.2.x

For contributors who need to know where a change belongs before making it. This page maps every
module in `kgmd/`, states the one-way dependency rule the package follows, and identifies the single
places that own reads, state, prompts, and data contracts.

## Module map

| Module | Responsibility |
|---|---|
| `kgmd/cli.py` | Click entry point (`main`) and every subcommand. Resolves the corpus and database path, opens connections, calls stage and query functions, and renders results as `rich` tables or as JSON. Contains no graph logic. |
| `kgmd/mcp_server.py` | MCP stdio server built on `FastMCP`. Registers the tool functions, resolves its connection and configuration from the client's working directory, and delegates each tool to `kgmd/query.py`. |
| `kgmd/query.py` | The read layer: `search_chunks`, `list_entities`, `get_entity`, `list_relations`, `get_neighbors`, `find_path`, `get_current_schema`. Takes a connection, returns plain `dict`/`list[dict]`. Builds a `networkx.DiGraph` in memory for traversal and pathfinding. |
| `kgmd/ingest.py` | Markdown discovery, sha256 content hashing, and chunking. `scan_corpus_files` is the single source of the resolved file set, composing `find_markdown_files` for `corpus.include` scoping, the `.kgmdignore` pass, and the dot-path rule, which is applied last and dominates both; `chunk_markdown` splits by paragraph, heading, or fixed window; `ingest_documents` calls `prune_missing_documents` to drop the rows of files that have left the corpus, then writes documents and chunks; `dry_run_report` is the read-only payload behind `kgmd build --dry-run`. |
| `kgmd/extract.py` | Extraction stage. Builds the extraction prompt with type and predicate vocabulary drawn from the existing graph, calls the LLM per chunk, and upserts entities, mentions, and relations under an `extraction_runs` row. |
| `kgmd/resolve.py` | Entity resolution. Clusters mention embeddings by cosine similarity, optionally asks the LLM to verify each cluster, then merges duplicate entities onto a survivor and records a `resolution_runs` row. |
| `kgmd/induce.py` | Schema induction. Summarises entity and relation statistics from the graph, asks the LLM for a typed schema, and stores the result as a new `schema_versions` row. |
| `kgmd/export.py` | Whole-graph serialisation: `export_jsonld`, `export_cypher`, `export_graphml`. Loads nodes and edges once through a shared `_load_graph` helper. Read-only. |
| `kgmd/llm.py` | The only `litellm` call site for completions. `call_structured` sends system and user messages, strips code fences, parses JSON into a pydantic model, retries with a corrective message on parse or validation failure, and appends a metadata-only line to the build log. |
| `kgmd/embed.py` | Embedding backends behind an `Embedder` protocol: `FastembedEmbedder` (local, the default) and `LitellmEmbedder` (provider API). `get_embedder` selects one from `embedding.backend`. `embed_new_chunks` and `embed_new_mentions` fill the vector tables incrementally. |
| `kgmd/db.py` | Connection ownership. `get_connection` opens SQLite, sets `row_factory`, loads the `sqlite-vec` extension, and applies `journal_mode = WAL`, `foreign_keys = ON`, `synchronous = NORMAL`. `init_db` runs the DDL once and sets `PRAGMA user_version = 1`. Also `check_embedding_model` and the `build_lock` context manager. |
| `kgmd/config.py` | `DEFAULT_CONFIG`, the platform-specific global config location via `platformdirs`, and `load_config`, which deep-merges built-in defaults, the global file, and the corpus `.kgmd/config.yaml`. |
| `kgmd/ignore.py` | `.kgmdignore` parsing. `load_ignore_rules` reads the corpus-root file into ordered rules with every pattern compiled to an anchored regex at parse time, `is_ignored` answers one corpus-relative path under last-match-wins ordering, and `DEFAULT_IGNORE_TEMPLATE` is the all-comments starter file `kgmd init` writes. Stdlib only; imports nothing from `kgmd` and issues no SQL. |
| `kgmd/schema.py` | `SCHEMA_SQL` (all tables, indexes, and the `current_schema` view), `vec_tables_sql(dim)` for the `vec0` virtual tables, `KV_DEFAULTS`, and the pydantic models used to validate LLM output. |
| `kgmd/prompts/` | Bundled prompt text assets: `extract.txt`, `resolve.txt`, `induce.txt`. Data, not code. |

## Dependency direction

Dependencies run one way only, from surfaces down to contracts:

```text
  surfaces    cli.py                       mcp_server.py
                 |                              |
                 +--------------+---------------+
                                v
  stages    ingest.py  extract.py  resolve.py  induce.py  export.py  query.py
                                |
                                v
  services          llm.py        embed.py        db.py
                                |
                                v
  contracts                  schema.py
```

The rules that follow from this:

- **Nothing imports `cli.py`.** It is a leaf consumed only by the `kgmd` console script
  (`kgmd = "kgmd.cli:main"`). A stage module that needs to print something is doing the surface's
  job.
- **Nothing imports `mcp_server.py`** except `cli.py`, from inside the `mcp` command body.
- **Stage modules never import each other.** `extract.py` and `resolve.py` depend on `llm.py` and
  `schema.py`; `induce.py` depends on `llm.py`; `ingest.py` imports `ignore.py` and nothing else;
  `export.py` and `query.py` import nothing from `kgmd` at all — they receive an open connection as
  their first argument.
- **`db.py` is the only module that imports `schema.py`** for DDL purposes, and `schema.py` imports
  nothing internal.
- **`config.py` is a leaf.** It is read by the surfaces and passed down as a plain `dict`; no stage
  module loads configuration for itself.
- **`ignore.py` is a leaf below `ingest.py`.** It is stdlib-only and imports nothing from `kgmd`, so
  the one-way direction extends as `ingest` -> `ignore` -> nothing. It parses text and answers
  questions about paths; it never sees a connection and issues no SQL.

`cli.py` imports `config`, `db`, `ingest`, and `query` at module level, and imports `embed`,
`extract`, `resolve`, `induce`, `export`, and `mcp_server` inside the command bodies that need them.
The effect is that `--help`, `kgmd stats`, and the read-only commands never load `fastembed` or the
extraction pipeline. Keep new heavy imports function-local for the same reason.

## One query layer, two surfaces

`kgmd/query.py` is the single read layer, and both user-facing surfaces sit on top of it. The CLI's
read commands and the MCP tools call the same functions with the same arguments:

| Read capability | `kgmd/query.py` | CLI command | MCP tool |
|---|---|---|---|
| Semantic chunk search | `search_chunks` | `kgmd find` | `search` |
| Entity listing | `list_entities` | `kgmd entities` | `list_entities_tool` |
| Single entity detail | `get_entity` | `kgmd entity` | `get_entity_tool` |
| Relation listing | `list_relations` | `kgmd relations` | `list_relations_tool` |
| Subgraph traversal | `get_neighbors` | `kgmd neighbors` | `get_neighbors_tool` |
| Shortest path | `find_path` | `kgmd path` | `find_path_tool` |
| Induced schema | `get_current_schema` | `kgmd schema` | `get_schema_tool` |

Every function returns plain dictionaries and lists of dictionaries — no ORM objects, no pydantic
models, no `sqlite3.Row` leaking out. That is what lets the CLI render a `rich` table, `--json` dump
the same structure with `json.dumps`, and the MCP server hand it to a client without a translation
layer.

Consequences for a change:

- Adding a read capability means adding a function to `query.py`, then exposing it from one or both
  surfaces. Putting the SQL in `cli.py` or `mcp_server.py` forks the behaviour between the two.
- Changing a returned shape changes both surfaces at once. Both the CLI reference and the MCP guide
  need updating in the same commit — see
  [Documentation is part of the change](./development.md#documentation-is-part-of-the-change).

## State

All persistent state is one SQLite file: `.kgmd/graph.db`.

- **`kgmd/schema.py` holds every statement of DDL.** `SCHEMA_SQL` defines `kv`, `documents`,
  `chunks`, `extraction_runs`, `entities`, `entity_mentions`, `relations`, `resolution_runs`,
  `schema_versions`, their indexes, and the `current_schema` view. `vec_tables_sql(dim)` defines the
  `sqlite-vec` virtual tables `vec_chunks` and `vec_entity_mentions`, dimensioned at creation time.
  No other module issues `CREATE`, `ALTER`, or `DROP`. That constrains call sites, not just
  definitions: `ingest.prune_missing_documents` binds the ids it is deleting in batched `IN (...)`
  clauses rather than staging them in a `TEMP TABLE`, because a temp table would be DDL outside
  `kgmd/schema.py`.
- **`kgmd/db.py` owns connections and their invariants.** Extension loading, pragmas, `PRAGMA
  user_version` as the migration marker, `KV_DEFAULTS` seeding, the embedding-model guard, and the
  `fcntl` exclusive lock at `.kgmd/build.lock` all live there. Stage modules receive a connection;
  they never open one.
- Because the vector tables are dimensioned when the database is created, and the embedding model is
  recorded in `kv`, changing the embedding model is a rebuild, not a migration.

## Prompts

Prompts are text assets, not string literals in code. The bundled files are:

| File | Used by |
|---|---|
| `kgmd/prompts/extract.txt` | `kgmd/extract.py` |
| `kgmd/prompts/resolve.txt` | `kgmd/resolve.py` |
| `kgmd/prompts/induce.txt` | `kgmd/induce.py` |

Each stage loads its prompt through the same two-step lookup: if `<corpus>/.kgmd/prompts/<name>.txt`
exists it is used, otherwise the bundled `kgmd/prompts/<name>.txt` is read. So a corpus can override
any prompt without a code change, and the override filename must match the bundled one exactly.

A new prompt is a new file in `kgmd/prompts/` plus the same lookup in the stage that consumes it.
Editing a bundled prompt changes extraction output for every corpus that has not overridden it, so
treat it as a behaviour change.

## Data contracts

Two kinds of shape exist in the package, and the boundary between them is deliberate:

- **Pydantic models, in `kgmd/schema.py`, validate LLM input and output only.**
  `ExtractedEntity`, `ExtractedRelation`, and `ExtractionResult` are the schema
  `kgmd/extract.py` asks `call_structured` to parse into; `ResolvedCluster` and `ResolutionResult`
  are the same for `kgmd/resolve.py`. Their job is to turn untrusted provider text into something
  with known fields, or raise.
- **Everything internal is a plain `dict` or a small dataclass.** `ingest.Chunk` is a dataclass;
  configuration is a nested `dict`; query results are dicts. Do not extend a pydantic model to carry
  internal state, and do not introduce a model for data that never crosses the provider boundary.

## Governing rules

The project's engineering principles are defined once, in
[`.specify/memory/constitution.md`](../../.specify/memory/constitution.md), which is authoritative
for all of them — this page describes structure only and deliberately does not restate a single
constitutional rule, so the two cannot diverge. Feature specifications, plans, and task lists live
in [`specs/`](../../specs/).

For the local check sequence and where tests for a change belong, see
[the development page](./development.md). For how a change reaches PyPI, see
[the release process](./release.md).
