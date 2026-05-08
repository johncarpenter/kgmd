# kgmd

A CLI that builds a knowledge graph from a directory of markdown files and exposes it via MCP.

- Extracts entities and relations using any LLM (via [litellm](https://github.com/BerriAI/litellm))
- Resolves duplicate entities using local embeddings + LLM verification
- Induces a typed schema from the extracted data
- Stores everything in a single SQLite file (powered by [sqlite-vec](https://github.com/asg017/sqlite-vec))
- Exposes the graph via CLI queries and an [MCP](https://modelcontextprotocol.io/) server

## Install

```bash
pip install kgmd
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv tool install kgmd
```

### Requirements

- Python 3.10+
- An API key for any LLM provider supported by litellm (OpenRouter, OpenAI, Anthropic, etc.)
- Embeddings run locally by default via [fastembed](https://github.com/qdrant/fastembed) (no API key needed)

## Quickstart

```bash
# Initialize a corpus
cd my-notes/
kgmd init

# Set your LLM API key
export OPENROUTER_API_KEY="sk-..."

# Build the knowledge graph (extract -> resolve -> induce)
kgmd build

# Query
kgmd entities
kgmd relations
kgmd find "machine learning"
kgmd entity "Brian Anderson"
kgmd neighbors "Brian Anderson" --depth 2
kgmd path "Brian Anderson" "Acme Corp"

# Export
kgmd export --format graphml --output graph.graphml

# View induced schema
kgmd schema

# Corpus statistics
kgmd stats
```

## How it works

`kgmd build` runs three stages:

1. **Extract** -- Each markdown file is chunked and sent to an LLM, which returns structured JSON with entities (people, organizations, projects, etc.) and relations between them.
2. **Resolve** -- Entity mentions are embedded locally, clustered by cosine similarity, and duplicate clusters are verified by the LLM before merging.
3. **Induce** -- Aggregate statistics about entity types and relation predicates are sent to the LLM, which produces a typed YAML schema with hierarchies.

All state lives in `.kgmd/graph.db`, a single SQLite file. Re-running `kgmd build` is incremental -- unchanged files are skipped.

## MCP Server

`kgmd mcp` launches an MCP server over stdio, exposing 7 tools:

| Tool | Description |
|---|---|
| `search` | Semantic search over chunks |
| `get_entity` | Full entity record with mentions and relations |
| `list_entities` | List entities, optionally filtered by type |
| `get_neighbors` | Subgraph traversal around an entity |
| `find_path` | Shortest path between two entities |
| `list_relations` | List relations with optional filters |
| `get_schema` | The current induced schema |

### Claude Desktop setup

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "kgmd": {
      "command": "kgmd",
      "args": ["mcp"],
      "cwd": "/path/to/your/corpus"
    }
  }
}
```

## Configuration

Per-corpus config lives in `.kgmd/config.yaml`. Global defaults in `~/.config/kgmd/config.yaml` (or the platform equivalent). Corpus config overrides global.

```yaml
embedding:
  backend: fastembed                    # or "litellm" for API embeddings
  model: BAAI/bge-small-en-v1.5

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
  similarity_threshold: 0.85
  llm_verify_clusters: true
  max_cluster_size: 10

induction:
  include_attribute_summary: true
  hierarchy_depth: 3
```

## Export formats

```bash
kgmd export --format jsonld   # JSON-LD with schema.org context
kgmd export --format cypher   # Cypher CREATE statements (Neo4j)
kgmd export --format graphml  # GraphML (Gephi, yEd)
```

## Development

```bash
git clone https://github.com/2lines/kgmd.git
cd kgmd
pip install -e .
make test    # run tests
make lint    # ruff check
make format  # ruff format
```

**Note:** Your Python must be built with SQLite extension loading enabled. If using pyenv:

```bash
LDFLAGS="-L$(brew --prefix sqlite)/lib" \
CPPFLAGS="-I$(brew --prefix sqlite)/include -DSQLITE_ENABLE_LOAD_EXTENSION" \
PYTHON_CONFIGURE_OPTS="--enable-loadable-sqlite-extensions" \
pyenv install 3.12
```

## License

[MIT](LICENSE)
