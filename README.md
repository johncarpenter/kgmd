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
- Your Python must be built with SQLite extension loading enabled — see
  [docs/install.md](docs/install.md) if `kgmd build` fails on extension loading

## Quickstart

```bash
cd my-notes/
kgmd init                        # create .kgmd/ (config, prompts, graph.db)
export OPENROUTER_API_KEY="sk-..."
kgmd build                       # extract -> resolve -> induce
kgmd stats                       # what got built
kgmd find "machine learning"     # semantic search
kgmd entity "Brian Anderson"     # one entity, with mentions and relations
kgmd neighbors "Brian Anderson" --depth 2
```

Full walkthrough: [docs/quickstart.md](docs/quickstart.md).

## How it works

`kgmd build` runs three stages:

1. **Extract** — each markdown file is chunked and sent to an LLM, which returns structured JSON with
   entities (people, organizations, projects, etc.) and relations between them.
2. **Resolve** — entity mentions are embedded locally, clustered by cosine similarity, and duplicate
   clusters are verified by the LLM before merging.
3. **Induce** — aggregate statistics about entity types and relation predicates are sent to the LLM,
   which produces a typed YAML schema with hierarchies.

All state lives in `.kgmd/graph.db`, a single SQLite file. Re-running `kgmd build` is incremental —
unchanged files are skipped. See [docs/concepts.md](docs/concepts.md).

## MCP server

`kgmd mcp` launches an MCP server over stdio exposing seven read-only tools over the graph. Setup,
the exact registered tool names, and client configuration are in
[docs/guides/mcp.md](docs/guides/mcp.md).

## Documentation

| Topic | Page |
|---|---|
| Install, prerequisites, credentials | [docs/install.md](docs/install.md) |
| Zero to a queryable graph | [docs/quickstart.md](docs/quickstart.md) |
| Pipeline stages and vocabulary | [docs/concepts.md](docs/concepts.md) |
| Every command and option | [docs/reference/cli.md](docs/reference/cli.md) |
| Every configuration setting | [docs/reference/configuration.md](docs/reference/configuration.md) |
| Export formats | [docs/reference/export.md](docs/reference/export.md) |
| MCP integration | [docs/guides/mcp.md](docs/guides/mcp.md) |
| Re-runs, cost, reset, backup | [docs/guides/maintenance.md](docs/guides/maintenance.md) |
| Troubleshooting | [docs/guides/troubleshooting.md](docs/guides/troubleshooting.md) |
| Worked examples | [docs/examples/personal-notes.md](docs/examples/personal-notes.md) |
| Contributing | [docs/contributing/development.md](docs/contributing/development.md) |

Index: [docs/README.md](docs/README.md).

## Development

```bash
git clone https://github.com/2lines/kgmd.git
cd kgmd
make install   # pip install -e ".[dev]"
make test      # pytest
make lint      # ruff check
make format    # ruff format
```

See [docs/contributing/development.md](docs/contributing/development.md) and
[docs/contributing/architecture.md](docs/contributing/architecture.md).

## License

[MIT](LICENSE)
