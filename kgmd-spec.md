# kgmd — Implementation Specification

**Status:** Specification for v1 implementation
**Audience:** Claude Code (implementer)
**Author intent:** A self-contained CLI that builds a knowledge graph from a directory of markdown files, exposes the result via MCP, and stores everything in a single SQLite database. No external services beyond the LLM provider.

---

## 1. Project Goals

Build a CLI tool, `kgmd`, that:

1. Ingests a directory of markdown files
2. Extracts entities and relations using an LLM
3. Resolves duplicate entities using local embeddings + LLM verification
4. Induces a schema (entity types, relation types, hierarchies) from the extracted data
5. Exposes the resulting knowledge graph via CLI queries and an MCP server
6. Stores all state in a single SQLite file per corpus

**Non-goals for v1:**

- Multi-user concurrent writes
- Distributed query
- Real-time/incremental file watching
- Web UI
- Cross-document coreference resolution
- Temporal/versioned graph (entities are global, latest extraction wins)
- Confidence calibration logic (raw scores stored; no reasoning over them)

---

## 2. Design Constraints

These are non-negotiable. Do not relax them without explicit approval.

- **Single binary, pip-installable.** `pip install kgmd` or `uv tool install kgmd` produces a working CLI.
- **Single SQLite file per corpus.** All state — documents, chunks, entities, relations, embeddings, schema versions, logs — lives in `.kgmd/graph.db`. No separate vector DB, no Neo4j, no Postgres.
- **Local-first embeddings.** Default embedding backend is `fastembed` (ONNX, CPU, ~50MB model). API embeddings are configurable but never required.
- **Pluggable LLM via `litellm`.** Users bring their own API key for any provider litellm supports. No SDK proliferation.
- **MCP transport is stdio only.** No HTTP, no auth, no port management.
- **Idempotent and incremental.** Re-running `kgmd build` on an unchanged corpus is a no-op. Changed files reprocess; unchanged files skip.
- **Pure Python dependencies.** All deps must have prebuilt wheels for macOS/Linux/Windows. No Rust/C compilation required at install.

---

## 3. Dependency List

```toml
[project]
name = "kgmd"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "click>=8.1",
    "litellm>=1.50",
    "sqlite-vec>=0.1.6",
    "fastembed>=0.4",
    "networkx>=3.2",
    "pydantic>=2.6",
    "mcp>=1.0",
    "pyyaml>=6.0",
    "rich>=13.7",
    "platformdirs>=4.0",
]

[project.scripts]
kgmd = "kgmd.cli:main"
```

Do not add additional dependencies without a written justification. If a stdlib alternative exists, use it.

---

## 4. Directory Layout

### Installed package layout

```
kgmd/
  __init__.py
  cli.py                    # click entry point, subcommand routing
  config.py                 # config loading, defaults
  db.py                     # SQLite + sqlite-vec connection management, migrations
  schema.py                 # SQL DDL, Pydantic models for graph entities
  ingest.py                 # markdown reading, chunking, hashing
  embed.py                  # fastembed wrapper + API fallback
  llm.py                    # litellm wrapper, retries, structured output parsing
  prompts.py                # default prompt templates
  extract.py                # extraction stage
  resolve.py                # entity resolution stage
  induce.py                 # schema induction stage
  query.py                  # graph queries (entities, relations, neighbors, paths)
  export.py                 # JSON-LD, Cypher, GraphML exporters
  mcp_server.py             # MCP stdio server
  prompts/                  # default prompt templates as files
    extract.txt
    resolve.txt
    induce.txt
```

### Corpus layout (created by `kgmd init`)

```
mycorpus/
  notes/                    # user's markdown files (any subdirs allowed)
    *.md
  .kgmd/
    graph.db                # SQLite database (the entire knowledge graph)
    config.yaml             # corpus-level config (model choice, chunk size, etc.)
    prompts/                # optional: user-overridden prompt templates
      extract.txt
      resolve.txt
      induce.txt
    logs/
      build.log
```

### Global config (created on first run)

```
~/.config/kgmd/config.yaml  # global defaults; per-corpus config overrides this
```

Use `platformdirs.user_config_dir("kgmd")` to locate this; do not hardcode `~/.config`.

---

## 5. SQLite Schema

All DDL goes in `kgmd/schema.py` as a single `SCHEMA_SQL` constant. Apply on first connection if not present. Use `PRAGMA user_version` for migrations (v1 = 1).

Always run with these pragmas on connection open:

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;
```

Load `sqlite-vec` extension on connection open via `sqlite_vec.load(conn)`.

### Tables

```sql
-- Source markdown files. Identity = absolute path; content tracked by hash.
CREATE TABLE documents (
    id              INTEGER PRIMARY KEY,
    path            TEXT NOT NULL UNIQUE,
    content_hash    TEXT NOT NULL,           -- sha256 of file content
    size_bytes      INTEGER NOT NULL,
    mtime           REAL NOT NULL,           -- file mtime at ingestion
    ingested_at     TEXT NOT NULL,           -- ISO8601 UTC
    last_extracted_hash TEXT                 -- content_hash at last successful extraction; NULL if never
);

CREATE INDEX idx_documents_path ON documents(path);
CREATE INDEX idx_documents_hash ON documents(content_hash);

-- Chunks of documents. Used for extraction and as evidence for relations.
CREATE TABLE chunks (
    id              INTEGER PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,        -- 0-based ordinal within document
    content         TEXT NOT NULL,
    char_start      INTEGER NOT NULL,        -- char offset in source document
    char_end        INTEGER NOT NULL,
    token_count     INTEGER,                 -- approximate, from tiktoken or len/4
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX idx_chunks_document ON chunks(document_id);

-- Canonical entities. One row per distinct real-world thing.
CREATE TABLE entities (
    id              INTEGER PRIMARY KEY,
    canonical_name  TEXT NOT NULL,           -- chosen representative surface form
    entity_type     TEXT NOT NULL,           -- e.g. "Person", "Organization", "Project"
    attributes      TEXT NOT NULL DEFAULT '{}',  -- JSON object, merged across mentions
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(canonical_name, entity_type)
);

CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_name ON entities(canonical_name);

-- Surface forms / mentions. Many-to-one with entities.
-- One row per (surface_form, entity_id) pair, with a list of mention chunks.
CREATE TABLE entity_mentions (
    id              INTEGER PRIMARY KEY,
    entity_id       INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    surface_form    TEXT NOT NULL,           -- as it appeared in source text
    chunk_id        INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    char_start      INTEGER,                 -- offset within chunk; nullable if LLM didn't return
    char_end        INTEGER,
    extraction_run_id INTEGER NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    confidence      REAL                     -- LLM-reported confidence, 0..1
);

CREATE INDEX idx_mentions_entity ON entity_mentions(entity_id);
CREATE INDEX idx_mentions_chunk ON entity_mentions(chunk_id);
CREATE INDEX idx_mentions_surface ON entity_mentions(surface_form);

-- Relations between entities. Directed.
CREATE TABLE relations (
    id              INTEGER PRIMARY KEY,
    subject_id      INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    predicate       TEXT NOT NULL,           -- e.g. "works_at", "founded", "discussed"
    object_id       INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    evidence_chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
    extraction_run_id INTEGER NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    confidence      REAL,
    attributes      TEXT NOT NULL DEFAULT '{}',  -- JSON, e.g. {"since": "2024"}
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_relations_subject ON relations(subject_id);
CREATE INDEX idx_relations_object ON relations(object_id);
CREATE INDEX idx_relations_predicate ON relations(predicate);
CREATE UNIQUE INDEX idx_relations_unique
    ON relations(subject_id, predicate, object_id, evidence_chunk_id);

-- Tracking table for extraction runs. One row per `kgmd extract` invocation.
CREATE TABLE extraction_runs (
    id              INTEGER PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    model           TEXT NOT NULL,           -- e.g. "openrouter/anthropic/claude-sonnet-4-5"
    status          TEXT NOT NULL,           -- "running", "completed", "failed"
    documents_processed INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT
);

-- Tracking for resolution runs.
CREATE TABLE resolution_runs (
    id              INTEGER PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    embedding_model TEXT NOT NULL,
    llm_model       TEXT NOT NULL,
    similarity_threshold REAL NOT NULL,      -- cosine threshold for cluster candidates
    merges          INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL
);

-- Versioned induced schemas. Every `kgmd induce` writes a new row.
-- `current` view always returns the latest.
CREATE TABLE schema_versions (
    id              INTEGER PRIMARY KEY,
    created_at      TEXT NOT NULL,
    llm_model       TEXT NOT NULL,
    schema_yaml     TEXT NOT NULL,           -- the full induced schema as YAML text
    entity_type_count INTEGER NOT NULL,
    relation_type_count INTEGER NOT NULL,
    notes           TEXT
);

CREATE VIEW current_schema AS
    SELECT * FROM schema_versions ORDER BY id DESC LIMIT 1;
```

### Vector tables (sqlite-vec)

```sql
-- Entity embeddings. One row per entity_mention surface form.
-- Used by resolve.py to find duplicate-candidate clusters.
-- Dimension: 384 for bge-small-en-v1.5 (the default fastembed model).
CREATE VIRTUAL TABLE vec_entity_mentions USING vec0(
    mention_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]
);

-- Chunk embeddings. One row per chunk. Used by `kgmd find` semantic search.
CREATE VIRTUAL TABLE vec_chunks USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]
);
```

If the configured embedding model has a different dimension, the schema initialization must read the dimension from `embed.get_dimension()` and substitute it into the DDL. Store the dimension in a `kv` table:

```sql
CREATE TABLE kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Initialize with `INSERT INTO kv VALUES ('embedding_dim', '384'), ('embedding_model', 'BAAI/bge-small-en-v1.5'), ('schema_version', '1');`

If a user changes embedding models mid-corpus, refuse to proceed and tell them to re-embed (`kgmd reembed`, out of scope for v1 — emit a clear error message instead).

---

## 6. Pipeline Stages

### 6.1 `kgmd init [--path PATH]`

Create `.kgmd/` directory in cwd (or `--path`). Write default `config.yaml`. Initialize SQLite database with schema. No-op if already initialized; print existing config.

Default `config.yaml`:

```yaml
embedding:
  backend: fastembed                    # or "litellm" for API
  model: BAAI/bge-small-en-v1.5         # fastembed model id
  # for litellm backend: model: text-embedding-3-small

llm:
  model: openrouter/anthropic/claude-sonnet-4-5
  temperature: 0.0
  max_tokens: 4096
  timeout_seconds: 120

chunking:
  max_chars: 4000
  overlap_chars: 200
  split_on: paragraph                   # or "heading", "fixed"

extraction:
  max_entities_per_chunk: 30
  max_relations_per_chunk: 30
  retry_on_parse_failure: 2

resolution:
  similarity_threshold: 0.85            # cosine threshold for candidate clusters
  llm_verify_clusters: true
  max_cluster_size: 10                  # clusters larger than this are split

induction:
  include_attribute_summary: true
  hierarchy_depth: 3
```

### 6.2 `kgmd build [PATH]`

Equivalent to `extract` → `resolve` → `induce` in sequence. PATH defaults to cwd.

### 6.3 `kgmd extract [PATH]`

For each `.md` file under PATH:

1. **Hash check.** Compute sha256 of file content. If `documents.last_extracted_hash` matches and no `--force`, skip the file. Print "skipped (unchanged): <path>".
2. **Ingest.** If new file or content changed, upsert into `documents`, delete old chunks for that document (cascade deletes mentions; relations are preserved if their chunk is still referenced via another document, but in practice this means relations from changed documents are removed and re-extracted).
3. **Chunk.** Split content into chunks per config.chunking. Insert into `chunks`.
4. **Embed chunks.** Compute embeddings for new chunks, insert into `vec_chunks`.
5. **Extract.** For each new chunk, call LLM with `prompts/extract.txt`. Parse structured JSON output (use Pydantic models defined in `schema.py`). On parse failure, retry up to `config.extraction.retry_on_parse_failure` with a "your previous output was not valid JSON, try again" reminder.
6. **Insert mentions and provisional entities.** Each extracted entity gets a row in `entities` (or matches existing by `(canonical_name, entity_type)`) and a row in `entity_mentions`. Each relation gets a row in `relations`.
7. **Embed new mention surface forms.** Insert into `vec_entity_mentions`.
8. **Update `documents.last_extracted_hash`.**

The extraction LLM prompt must request JSON with this exact shape:

```json
{
  "entities": [
    {
      "surface_form": "Brian Anderson",
      "canonical_name": "Brian Anderson",
      "entity_type": "Person",
      "attributes": {"role": "CFO"},
      "char_start": 142,
      "char_end": 156,
      "confidence": 0.95
    }
  ],
  "relations": [
    {
      "subject": "Brian Anderson",
      "predicate": "works_at",
      "object": "CFO Centre Canada",
      "attributes": {},
      "confidence": 0.9
    }
  ]
}
```

The prompt template should:

- Pass the chunk text as input
- Pass the existing entity-type vocabulary (top 50 most-common types from `entities`) as a soft constraint to encourage type reuse, but explicitly allow new types
- Pass the existing relation-predicate vocabulary similarly
- Require JSON output only, no prose

Define Pydantic models for parsing in `schema.py`:

```python
class ExtractedEntity(BaseModel):
    surface_form: str
    canonical_name: str
    entity_type: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    char_start: int | None = None
    char_end: int | None = None
    confidence: float | None = None

class ExtractedRelation(BaseModel):
    subject: str
    predicate: str
    object: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None

class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]
```

### 6.4 `kgmd resolve`

Goal: merge entities that refer to the same real-world thing.

1. **Load all entity mentions with embeddings.** Query `entity_mentions` joined with `vec_entity_mentions`.
2. **Cluster.** For each mention, find all other mentions with cosine similarity ≥ `config.resolution.similarity_threshold` AND same `entity_type`. Build connected components (union-find).
3. **Filter clusters.** Drop singletons. Cap clusters at `config.resolution.max_cluster_size`; if larger, split by sub-clustering at threshold + 0.05.
4. **LLM verification.** For each cluster, send the surface forms + a sample of attributes + 1 short evidence snippet per mention to the LLM. Prompt asks: "are these all the same entity? if not, partition them." Parse JSON response with the same Pydantic-strict approach as extraction.
5. **Merge.** For each verified cluster:
   - Choose canonical name (LLM picks from cluster, or default to most-frequent surface form)
   - Pick the lowest-id entity as the survivor
   - Update all mentions to point to survivor
   - Merge `attributes` JSON (later mentions overwrite earlier on key collision; record collisions in build log)
   - Update all relations referencing dropped entity ids to reference survivor
   - Delete dropped entity rows
   - Run `INSERT OR IGNORE` semantics on `relations` after rewrite to deduplicate
6. **Log.** Insert row in `resolution_runs` with merge count.

### 6.5 `kgmd induce`

Goal: produce a typed schema from the resolved graph.

1. **Aggregate.** Compute statistics:
   - Entity types and counts
   - For each entity type: top 20 attribute keys with frequency
   - Relation predicates and counts
   - For each predicate: distribution of (subject_type, object_type) pairs
2. **LLM call.** Send the aggregated stats to the LLM with `prompts/induce.txt`. Ask for:
   - A YAML schema with entity types, their attributes (key + inferred type from sampled values), and a hierarchy (parent type → child types) up to `config.induction.hierarchy_depth` levels
   - Relation types with allowed subject and object types
   - Brief natural-language descriptions for each type
3. **Validate.** Parse the YAML. Confirm every entity type and predicate in the live database appears somewhere in the schema (either directly or as a child of a hierarchy node). If not, re-prompt once with the missing types listed.
4. **Persist.** Insert into `schema_versions`. Print summary (counts, hierarchy outline) via `rich`.

The prompt should produce output in this shape:

```yaml
version: 1
generated_at: 2026-05-07T19:30:00Z
entity_types:
  Person:
    description: An individual human.
    attributes:
      role: {type: string, frequency: 0.42}
      email: {type: string, frequency: 0.18}
    parent: null
    children: [Contact, Investor]
  Contact:
    parent: Person
    description: A person with whom the user has corresponded.
    attributes: {}
    children: []
relation_types:
  works_at:
    description: Employment relationship.
    subject_types: [Person]
    object_types: [Organization]
    frequency: 87
```

---

## 7. Query Commands

All commands accept `--json` for machine-readable output. Default is `rich`-formatted tables.

- `kgmd entities [--type TYPE] [--limit N] [--search QUERY]`
   - List entities, optionally filtered by type or substring match on canonical_name
- `kgmd relations [--predicate PRED] [--subject NAME] [--object NAME] [--limit N]`
- `kgmd find QUERY [--limit N]`
   - Semantic search over chunks via `vec_chunks`. Returns top-N chunks with their associated entities.
- `kgmd entity NAME [--type TYPE]`
   - Show full record for a single entity: canonical name, type, attributes, all mentions, all incoming and outgoing relations.
- `kgmd neighbors NAME [--depth N] [--type TYPE]`
   - Subgraph traversal up to depth N. Use NetworkX loaded from SQLite.
- `kgmd path FROM TO [--max-depth N]`
   - Shortest path between two entities. NetworkX `shortest_path`.
- `kgmd schema`
   - Pretty-print the current induced schema.
- `kgmd stats`
   - Document count, chunk count, entity counts by type, relation counts by predicate, last extraction run, last resolution run.

---

## 8. Export

`kgmd export --format FMT [--output PATH]`

Formats:

- `jsonld` — JSON-LD with entities as nodes and relations as edges. Use `@context` mapping types to schema.org where reasonable.
- `cypher` — Newline-delimited Cypher `CREATE` statements suitable for `cypher-shell < graph.cypher`.
- `graphml` — XML format readable by Gephi, yEd. Use NetworkX `write_graphml`.

Default output is stdout if `--output` omitted.

---

## 9. MCP Server

`kgmd mcp` launches an MCP server over stdio. Use the `mcp` Python package. Server name: `kgmd`. Description: "Local knowledge graph over your markdown corpus."

Expose these tools:

| Tool name | Args | Returns |
|---|---|---|
| `search` | `query: str, limit: int = 10` | List of `{chunk_text, document_path, entities}` |
| `get_entity` | `name: str, type: str = None` | Entity record with attributes, mentions, relations |
| `list_entities` | `type: str = None, limit: int = 50` | List of entity summaries |
| `get_neighbors` | `name: str, depth: int = 1` | Subgraph as `{nodes: [...], edges: [...]}` |
| `find_path` | `from_name: str, to_name: str, max_depth: int = 5` | List of edges, or `null` if no path |
| `list_relations` | `predicate: str = None, subject: str = None, object: str = None, limit: int = 50` | List of relation records |
| `get_schema` | (none) | The current induced schema as a JSON-converted dict |

The MCP server reads `.kgmd/graph.db` from cwd. If not present, return a clear error.

---

## 10. LLM Output Parsing

Wrap every LLM call in a "structured output" helper in `llm.py`:

```python
def call_structured(
    model: str,
    system: str,
    user: str,
    response_model: type[BaseModel],
    max_retries: int = 2,
) -> BaseModel:
    """
    Call litellm, expect JSON output, parse into the given Pydantic model.
    On JSONDecodeError or ValidationError, append a corrective message and retry.
    Raise after max_retries.
    """
```

Implementation notes:

- Always set `response_format={"type": "json_object"}` for providers that support it (OpenAI, Anthropic via litellm, OpenRouter for compatible models). Fall back to relying on the prompt for providers that don't.
- Strip markdown code fences (```json ... ```) before parsing — common LLM behavior.
- Log every LLM call (model, prompt token count, response token count, latency, success/failure) to `.kgmd/logs/build.log`.

---

## 11. Embedding Backend

`embed.py` provides:

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def get_dimension(self) -> int: ...
    def model_id(self) -> str: ...

def get_embedder(config: dict) -> Embedder: ...
```

Two implementations:

- `FastembedEmbedder` — wraps `fastembed.TextEmbedding`. Default model: `BAAI/bge-small-en-v1.5` (384 dims). Cache the model instance.
- `LitellmEmbedder` — wraps `litellm.embedding`. Reads dimension from a first call response, caches it.

Embedding batches: cap at 64 texts per call for fastembed, 96 for litellm. Show progress via `rich.progress` for batches > 1.

---

## 12. Chunking

`ingest.py` implements:

```python
def chunk_markdown(text: str, max_chars: int, overlap_chars: int, split_on: str) -> list[Chunk]:
    """
    Returns chunks with their character offsets in the source.
    
    split_on:
      "paragraph": split on double newlines, then merge adjacent paragraphs
                   until adding the next would exceed max_chars.
      "heading":   split on markdown headings (# ## ###), then apply same merging.
      "fixed":     fixed-size windows with overlap.
    
    For "paragraph" and "heading", overlap_chars is ignored (chunks are
    semantically bounded). For "fixed", overlap is honored.
    """
```

Token counting is approximate: `len(text) // 4` is acceptable. Do not pull in `tiktoken` unless the LLM provider needs exact counts (it doesn't, for our use).

---

## 13. CLI Implementation

Use `click`. Top-level command group with subcommands. Every command accepts `--db PATH` to override the default `.kgmd/graph.db` location, and `--config PATH` to override the default config.

Always:

- Use `rich.console.Console` for output, with `--json` flag forcing plain JSON.
- On error, print a clear message via `rich`, exit code 1. No tracebacks unless `--debug`.
- Confirm destructive operations (`kgmd reset`, future `kgmd reembed`) with `click.confirm`.

---

## 14. Concurrency

SQLite WAL mode is enabled. Multi-reader is fine. Multi-writer is not.

Use a file lock (`.kgmd/build.lock`) for `build`, `extract`, `resolve`, `induce`. If the lock exists and the holder PID is alive, refuse to start. If the holder PID is dead, log a warning and reclaim. Use `fcntl.flock` on Unix, fall back gracefully on Windows.

The MCP server does not take the lock (read-only).

---

## 15. Testing

Use `pytest`. Tests go in `tests/`. Required test coverage:

- `test_db.py` — schema creation, migrations, vec extension load
- `test_chunk.py` — paragraph/heading/fixed chunking on canned markdown
- `test_extract.py` — extraction with a mocked litellm response (use `pytest-mock`)
- `test_resolve.py` — clustering with a fixed similarity matrix; LLM verification mocked
- `test_induce.py` — schema induction with mocked LLM
- `test_query.py` — neighbors, paths, find against a seeded fixture DB
- `test_export.py` — round-trip JSON-LD and GraphML on a fixture
- `test_mcp.py` — MCP tool invocations against a seeded fixture DB

Provide a `tests/fixtures/` directory with a small markdown corpus (5–10 files) for integration tests. Keep fixture corpus in the repo.

Do not test against real LLM APIs in CI. All LLM calls are mocked.

---

## 16. Build & Distribution

- Use `pyproject.toml` with `hatchling` backend. Reason: it's stdlib-friendly and produces clean wheels.
- Single source of truth for version: `kgmd/__init__.py` `__version__` string, read by `pyproject.toml` via `dynamic = ["version"]`.
- Add a `Makefile` with: `make install`, `make test`, `make lint`, `make format`, `make build`. Use `ruff` for lint and format. Do not use black + isort.
- README.md must include: install instructions, quickstart (init → build → query), config reference, MCP setup snippet for Claude Desktop.

---

## 17. Implementation Order

Build in this order. Each phase should leave the codebase in a working, testable state.

1. **Skeleton + DB.** `cli.py` with `kgmd init`, `db.py`, `schema.py` DDL, `kgmd stats` returning zero counts. Verify sqlite-vec loads.
2. **Ingestion + chunking.** `ingest.py`, `kgmd build` reads files, hashes, chunks, inserts. No extraction yet. `kgmd stats` shows real numbers.
3. **Embeddings.** `embed.py` with fastembed. Embed chunks during ingestion. `kgmd find QUERY` works.
4. **Extraction.** `llm.py`, `extract.py`, `prompts/extract.txt`. End-to-end: build produces entities and relations. `kgmd entities` and `kgmd relations` work.
5. **Resolution.** `resolve.py`, `prompts/resolve.txt`. Embed mentions, cluster, LLM-verify, merge.
6. **Induction.** `induce.py`, `prompts/induce.txt`. Generate and store schema. `kgmd schema` works.
7. **Graph queries.** `query.py` with NetworkX. `neighbors`, `path`, `entity` commands.
8. **Export.** `export.py` with three formats.
9. **MCP server.** `mcp_server.py`. Wire to the same query layer used by CLI.
10. **Polish.** Logging, error messages, docstrings, README, tests filled to coverage targets.

---

## 18. Out-of-Scope Reminders

If the implementation seems to need any of these, stop and ask:

- A web UI of any kind
- Authentication
- Multi-tenant support
- Real-time file watching (no `watchdog` dependency)
- Cross-document coreference
- A proper migration system beyond `PRAGMA user_version` checks
- Streaming LLM responses
- Embedding model swap mid-corpus

---

## 19. Definition of Done

v1 ships when:

- `pip install -e .` works on a clean Python 3.10+ venv on macOS and Linux
- The full quickstart in the README runs end-to-end on the fixture corpus without errors
- `pytest` passes with no skips
- `kgmd build` on a 100-file markdown corpus completes without manual intervention and produces sensible entities, relations, and a schema
- `kgmd mcp` connects successfully to Claude Desktop and all 7 tools respond correctly
- `kgmd export --format graphml` produces a file that opens in Gephi
