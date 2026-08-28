# Install
> Applies to kgmd 0.1.x

For anyone putting kgmd on a machine for the first time. By the end you will have the `kgmd`
command available, a verified interpreter that can load SQLite extensions, and — if you intend to
build a graph rather than only query one — a provider credential in your environment.

## Requirements

- **Python 3.10, 3.11, 3.12, or 3.13.** The package declares `requires-python = ">=3.10"` and those
  four versions are the ones tested in CI.
- **An interpreter that can load SQLite extensions.** Non-negotiable; see
  [Loadable SQLite extensions](#loadable-sqlite-extensions) below for the check and the fix.
- **An LLM provider credential** — needed only by the build stages (extraction, duplicate
  verification, schema induction), not by queries.
- **Network access.** The build stages call your provider, and the first build downloads the local
  embedding model.

Embeddings run locally by default through [fastembed](https://github.com/qdrant/fastembed) with
`BAAI/bge-small-en-v1.5` (384 dimensions), so there is no embedding credential to obtain and no
embedding API to pay for. Only the LLM stages talk to a paid provider.

Everything kgmd needs beyond that is an ordinary Python dependency (`click`, `litellm`,
`sqlite-vec`, `fastembed`, `networkx`, `pydantic`, `mcp`, `pyyaml`, `rich`, `platformdirs`) and is
installed for you.

## Install

From PyPI:

```bash
pip install kgmd
```

With [uv](https://github.com/astral-sh/uv), which puts the command on your PATH in its own isolated
environment:

```bash
uv tool install kgmd
```

From a source checkout, for hacking on kgmd itself:

```bash
git clone https://github.com/johncarpenter/kgmd.git
cd kgmd
pip install -e ".[dev]"
```

The editable install adds the `pytest`, `pytest-mock`, and `ruff` development extras. See
[Development](./contributing/development.md) for the local check sequence.

## Verify the install

`kgmd --help` needs no corpus, no database, and no credential. It is the cheapest proof that the
entry point resolved:

```bash
kgmd --help
```

```text
Usage: kgmd [OPTIONS] COMMAND [ARGS]...

  kgmd — Knowledge graph from markdown files.

Options:
  --debug  Show full tracebacks on error.
  --help   Show this message and exit.

Commands:
  build      Build the knowledge graph: extract, resolve, induce.
  entities   List entities.
  entity     Show full record for a single entity.
  export     Export the knowledge graph.
  extract    Extract entities and relations from documents.
  find       Semantic search over chunks.
  induce     Induce schema from the knowledge graph.
  init       Initialize a new kgmd corpus.
  mcp        Launch MCP server over stdio.
  neighbors  Subgraph traversal around an entity.
  path       Find shortest path between two entities.
  relations  List relations.
  reset      Reset the knowledge graph, keeping config and prompts.
  resolve    Resolve duplicate entities.
  schema     Show the current induced schema.
  stats      Show corpus statistics.
```

Sixteen commands and the single global option `--debug`. Every other command resolves a database
first, so `--help` is the only one that proves nothing about SQLite. For that, run the check in the
next section.

## Loadable SQLite extensions

kgmd stores the whole graph, including vector indexes, in one SQLite file and reaches the vector
tables through the [sqlite-vec](https://github.com/asg017/sqlite-vec) extension. Every database
connection kgmd opens goes through `get_connection` in `kgmd/db.py`, which calls
`enable_load_extension(True)`, loads sqlite-vec, then turns extension loading off again. If your
interpreter's `sqlite3` module was compiled without loadable-extension support, that call cannot
succeed and **no kgmd command that touches the database will work** — not `kgmd init`, not
`kgmd build`, not a single query.

Check before you go further:

```bash
python -c "import sqlite3; print(hasattr(sqlite3.connect(':memory:'), 'enable_load_extension'))"
```

A capable interpreter prints `True`.

**Symptom of an incapable interpreter.** CPython only defines
`sqlite3.Connection.enable_load_extension` when it was configured with loadable-extension support,
so on a build without it the very first command that opens the database — usually `kgmd init` —
fails with an `AttributeError` naming `enable_load_extension`. Because errors are rendered as a
single line unless you pass `--debug`, you see one `Error:` line rather than a stack. Re-run with
`kgmd --debug init` and the traceback ends inside `get_connection` in `kgmd/db.py`. A related
variant is an `OperationalError` raised while sqlite-vec is being loaded, when the attribute exists
but the underlying SQLite library refuses the load.

**Remedy.** Rebuild the interpreter with extension loading enabled. This failure is characteristic
of pyenv-built interpreters, which by default compile against a SQLite that has the feature turned
off:

```bash
LDFLAGS="-L$(brew --prefix sqlite)/lib" \
CPPFLAGS="-I$(brew --prefix sqlite)/include -DSQLITE_ENABLE_LOAD_EXTENSION" \
PYTHON_CONFIGURE_OPTS="--enable-loadable-sqlite-extensions" \
pyenv install 3.12
```

On macOS the Homebrew (`brew install python`) and python.org installers generally ship interpreters
that already have the feature enabled, as do the system packages on mainstream Linux distributions.
If you have a choice, install kgmd under one of those rather than rebuilding.

## Provider credentials

The build stages call your LLM provider through [litellm](https://github.com/BerriAI/litellm), which
reads provider credentials implicitly from the environment. kgmd itself never reads, prompts for,
stores, or logs a credential — it passes a model id to litellm and lets litellm find the key.

```bash
export OPENROUTER_API_KEY="sk-..."
```

The default model is `openrouter/anthropic/claude-sonnet-4-5`, which is why `OPENROUTER_API_KEY` is
the usual variable. Any model id litellm can route works; set `llm.model` in your configuration and
export whatever variable that provider expects. See the
[Configuration reference](./reference/configuration.md) for the key, its precedence rules, and the
location of the global configuration file.

Put the `export` in your shell profile or a secret manager rather than in a committed file. The run
log at `.kgmd/logs/build.log` records metadata only — one line per provider call with the model id,
prompt and response character counts, elapsed seconds, and whether the call succeeded. Prompt text,
response bodies, and credentials are never written to it.

## What works without a credential

Once a graph exists, everything that only reads it runs offline apart from the local embedding
model:

- `kgmd init` — creates `.kgmd/` and an empty database.
- `kgmd stats`, `kgmd entities`, `kgmd relations`, `kgmd entity`, `kgmd neighbors`, `kgmd path`,
  `kgmd schema` — pure reads over SQLite.
- `kgmd find` — embeds the query with the local fastembed model, so no provider is involved.
- `kgmd export` — writes JSON-LD, Cypher, or GraphML from data already in the database.
- `kgmd reset` — clears graph data.
- `kgmd mcp` — serves the same read-only queries to an assistant.

Only `kgmd build` and its three individual stages (`kgmd extract`, `kgmd resolve`, `kgmd induce`)
need a provider credential.

## Next

Go to the [Quickstart](./quickstart.md) and turn a directory of notes into a queryable graph.
