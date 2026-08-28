# Walkthrough: Ask Questions Through an Assistant
> Applies to kgmd 0.2.x

For anyone who already has a built kgmd corpus and wants to ask about it in natural language instead
of composing CLI invocations. By the end an MCP-capable assistant will be wired to your graph, you
will know which of the seven registered tools each kind of question exercises, and you will
recognize the one misconfiguration that accounts for most failures.

## Goal

Expose an existing `.kgmd/graph.db` to an MCP client over stdio with `kgmd mcp`, then ask questions
in prose and let the client choose the tools. The server is read-only: it answers from whatever the
last build produced and never writes to the graph.

## Prerequisites

- kgmd 0.2.0 installed and on `PATH`, and a corpus you have already built with `kgmd build`. The
  walkthrough in [personal-notes.md](./personal-notes.md) produces one; so does
  [quickstart.md](../quickstart.md).
- An MCP-capable client that can launch a stdio server with a working directory — Claude Desktop,
  Claude Code, or any other MCP host.
- **No git checkout is required.** The installed wheel provides `kgmd mcp`. A checkout is only
  needed if you want to build the graph from the seven sample notes under `tests/fixtures/`, which
  are test fixtures and are not shipped in the wheel.
- **No provider credential is required by the server.** None of the seven tools makes an LLM call.
  `search` embeds the query locally with the corpus embedding model (default `fastembed` running
  `BAAI/bge-small-en-v1.5`); every other tool is a SQL read. A credential is only needed for
  `kgmd build`, which is a separate step you run from the shell.

## Corpus

Reuse the corpus from [personal-notes.md](./personal-notes.md) — your own notes directory containing
`.kgmd/graph.db`. For a reproducible session, use a graph built from the seven fixture notes in a
git checkout (`tests/fixtures/acme_corp.md`, `tests/fixtures/brian_anderson.md`,
`tests/fixtures/digital_transformation.md`, `tests/fixtures/partnerships.md`,
`tests/fixtures/quarterly_review.md`, `tests/fixtures/sarah_chen.md`,
`tests/fixtures/tech_stack.md`); the example questions below are written against those notes.
Nothing in this page needs a second copy of the corpus — the server reads the same database the CLI
does.

## Steps

### 1. Confirm the graph exists and is populated

```bash
cd ~/notes
kgmd stats
```

The server resolves its database as `.kgmd/graph.db` **relative to its own working directory**, and
raises `No kgmd database found at` when that file is absent. Run `kgmd stats` in the directory you
intend to hand the client, and check that entities and relations are non-zero. Zero entities means
the build never got past ingestion; re-run `kgmd build` before wiring up the client.

### 2. Register the server with your client

`kgmd mcp` speaks MCP over stdio and takes no options, so the entire configuration is the command,
its single argument, and the working directory:

```json
{
  "mcpServers": {
    "kgmd": {
      "command": "kgmd",
      "args": ["mcp"],
      "cwd": "~/notes"
    }
  }
}
```

`cwd` must be the corpus directory — the one that contains `.kgmd/`, not `.kgmd/` itself. Unlike the
CLI, the server does **not** walk up the tree looking for a corpus; it checks exactly
`<cwd>/.kgmd/graph.db`. If your client does not expand `~`, write the fully expanded path to the
corpus directory. To serve two corpora, register two entries under different names, each with its
own `cwd`.

Client config file locations and the per-tool reference live in [mcp.md](../guides/mcp.md).

### 3. Restart the client and check the tool list

Most clients read server configuration only at startup. After restarting, the server should appear
with seven tools:

```text
search
get_entity_tool
list_entities_tool
get_neighbors_tool
find_path_tool
list_relations_tool
get_schema_tool
```

Those are the registered names, byte for byte. The `_tool` suffix is real: `kgmd/mcp_server.py`
already imports `get_entity`, `list_entities`, `get_neighbors`, `find_path`, `list_relations`, and
`get_current_schema` from `kgmd.query`, so the tool functions that wrap them are named apart to
avoid shadowing. Only `search` has no suffix. If a client or an older document offers you
`get_entity` or `find_path`, those names do not exist.

### 4. Ask questions

Three questions, one per traversal style. The client picks the tool; the mapping below is what each
question is designed to trigger.

**"What do my notes say about the data pipeline?"** — exercises `search(query, limit=10)`. The
server embeds the question with the corpus embedding model, runs a nearest-neighbour query over
chunk vectors, and returns matching chunks each carrying `chunk_text`, `document_path`, and the
`entities` mentioned in that chunk.

**"Who does Sarah Chen work with, two hops out?"** — exercises `get_neighbors_tool(name, depth=2)`.
The name must be the canonical entity name; when the assistant guesses wrong it typically recovers
with `list_entities_tool(type="Person")` to see the real names, or `get_entity_tool(name)` to pull
one full record with its aliases and relations.

**"How are Sarah Chen and CFO Centre Canada connected?"** — exercises
`find_path_tool(from_name, to_name, max_depth=5)`, which returns the hops of a shortest path or the
string `No path found between` when there is none within the depth limit.

Two more tools cover inventory questions: `list_relations_tool(predicate, subject, object, limit)`
answers "list everything that reports to X" style filters, and `get_schema_tool()` — which takes no
parameters — answers "what kinds of things and links are in this graph" from the induced schema.

## Expected output

You never see the raw tool results in the client; you see what the assistant does with them. What
each tool hands back, and therefore what the assistant can say:

| Tool | Result | What the assistant can do with it |
|---|---|---|
| `search` | list of chunks, each with `chunk_text`, `document_path`, `entities` | Quote or paraphrase the passage and cite the note it came from. Chunk text is the whole chunk, not a snippet. |
| `get_entity_tool` | record with `name`, `type`, `attributes`, `mentions`, `outgoing_relations`, `incoming_relations`, or a not-found string naming the entity | Summarize one thing, list its aliases from the mention surface forms, and state its relations in both directions. |
| `list_entities_tool` | list of `{id, name, type, attributes}`, name-ordered, capped at `limit` (default 50) | Enumerate candidates, recover from a wrong name, or answer "who is in here". |
| `get_neighbors_tool` | `{"nodes": [...], "edges": [...]}` for the subgraph within `depth` | Describe a neighbourhood. Edges carry `source`, `target`, `predicate`, `confidence` in stored direction, so an inbound edge reads with the outside entity as subject. |
| `find_path_tool` | list of hop objects with `source`, `target`, `predicate`, or a not-found string | Narrate a chain of connections. The path is computed on the undirected graph, so a hop can read against the direction of travel. |
| `list_relations_tool` | list of relations with `subject`, `subject_type`, `predicate`, `object`, `object_type`, `confidence`, `attributes` | Answer filtered questions without traversal, and report confidence. The `subject` and `object` filters are exact canonical-name matches, not substrings. |
| `get_schema_tool` | induced schema with `entity_type_count`, `relation_type_count`, the schema body, and the model that induced it, or `No schema has been induced yet.` | Explain the vocabulary of the graph before drilling into instances. |

A well-behaved client chains these: `search` to locate the topic, `get_entity_tool` to resolve the
thing it found, then `get_neighbors_tool` or `find_path_tool` to explain how it relates to
everything else. Answers are grounded in your notes because every tool result carries either a
document path or a canonical entity name.

The `search` tool is the only one that loads the embedding model. On a cold start the first search
in a session pays the model load; subsequent calls in the same server process do not.

## Limitations

- **The server is read-only.** There is no tool that ingests, extracts, resolves, or induces. New
  notes reach the assistant only after you run `kgmd build` from a shell; the server then sees the
  updated database on its next query, since each call opens a fresh connection.
- **`cwd` is load-bearing.** A wrong or missing working directory fails every tool call with
  `No kgmd database found at` followed by the path it tried and a reminder to run `kgmd init` and
  `kgmd build`. The path in that message is the fastest way to see which directory your client
  actually launched the server in.
- **Tool names carry the `_tool` suffix.** Six of the seven are `get_entity_tool`,
  `list_entities_tool`, `get_neighbors_tool`, `find_path_tool`, `list_relations_tool`, and
  `get_schema_tool`; only `search` is bare. Any name without the suffix except `search` is not
  registered.
- **Names must be canonical.** `get_entity_tool`, `get_neighbors_tool`, and `find_path_tool` match
  on the canonical entity name, not on aliases or substrings. An alias that resolution folded into
  another entity is stored as a mention surface form and will not match; `list_entities_tool` is the
  way back.
- **stdio only.** `kgmd mcp` runs a stdio transport; there is no HTTP or SSE listener and no port to
  configure, so the client must be able to spawn a local process.
- **One corpus per server entry.** The database path is derived from the process working directory,
  which the client fixes at launch. Serving several corpora means several registered entries.
- **The graph is only as current as the last build.** `get_schema_tool` returns its "no schema"
  string until an induction has run, and every tool reflects the state of the last `kgmd build` —
  notes written or edited since then are invisible until you build again. That cuts both ways: a
  note you deleted, renamed, or newly excluded with `.kgmdignore` before that build is gone from the
  graph, so no tool will answer from it.
