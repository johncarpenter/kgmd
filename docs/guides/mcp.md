# MCP Server
> Applies to kgmd 0.2.x

For anyone who wants an MCP-capable assistant to read a built kgmd graph. By the end of this page you
will have a client configured against a corpus, you will know the exact name and signature of all
seven registered tools, and you will know why the client's working directory decides which graph gets
served.

## Setup

`kgmd mcp` starts an MCP server that speaks the stdio transport. It takes no options: it reads no
`--db` flag and no arguments, and it never prints a banner, because stdout is the protocol channel.
You do not run it yourself — the MCP client launches it as a subprocess.

A minimal Claude Desktop entry:

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

Replace `~/notes` with the corpus directory — the directory that contains `.kgmd/`, not the `.kgmd/`
directory itself. Not every client expands `~` in `cwd`; if yours does not, write the full path to the
corpus. If `kgmd` is not on the `PATH` your client inherits, set `command` to the full path of the
`kgmd` executable inside the environment you installed it into.

Client configuration file locations:

| Platform | Claude Desktop config file |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | Not verified here. Claude Desktop's Linux packaging is outside what this repository can check, so consult your client's own documentation rather than trusting a guess. |

Other MCP clients use their own config file, but the three fields are the same everywhere: a command,
its arguments, and a working directory. Restart the client after editing its config; MCP servers are
launched at client start-up.

## Working directory matters

The server resolves its database as `Path.cwd() / ".kgmd" / "graph.db"` — the process working
directory, and only that directory. Unlike the CLI, it does **not** walk parent directories looking
for a `.kgmd/`, and it has no flag to point somewhere else. The `cwd` you give the client is therefore
load-bearing: it is the entire database selection mechanism.

If `cwd` is wrong, missing, or points at a directory that was never initialized, every tool call
fails with `No kgmd database found at` followed by the path it tried and a reminder to run `kgmd init`
and `kgmd build`. The path in that message is the fix: it tells you exactly which directory the
client actually started the server in.

Three things to check when you see it:

1. The `cwd` in the client config names the corpus root, not `.kgmd/` and not a parent.
2. `.kgmd/graph.db` exists in that directory. `kgmd init` creates it; it is empty until `kgmd build`
   populates it.
3. Nothing in the client is rewriting relative paths. Absolute paths remove the doubt.

The configuration file is read from the same place — `load_config(Path.cwd())` — so a corpus-level
`.kgmd/config.yaml` only applies when `cwd` is right. A wrong `cwd` silently falls back to the global
config and built-in defaults for the one tool that reads config at all, `search`.

## A note on tool names

Six of the seven registered names end in `_tool`: `get_entity_tool`, `list_entities_tool`,
`get_neighbors_tool`, `find_path_tool`, `list_relations_tool`, `get_schema_tool`. Only `search` has no
suffix.

The suffix is not decorative. `kgmd/mcp_server.py` imports `get_entity`, `list_entities`,
`get_neighbors`, `find_path`, `list_relations` and `get_current_schema` from `kgmd.query`, and each
tool wraps the same-named import; the suffix keeps the wrapper from shadowing what it calls. `search`
needs no suffix because the underlying query function is named `search_chunks`.

Earlier revisions of the project README listed the suffix-free spellings. Those names are not
registered with the server. A client calling `get_entity` or `list_relations` gets an unknown-tool
error. The names in the sections below are the registered ones.

## Tools

Every tool opens its own connection, runs read-only SQL, and closes the connection before returning.
Optional parameters map to SQL filters; omitting one means no filter on that column.

### search

Semantic search over the markdown corpus. Returns matching chunks with entities.

| Parameter | Type | Default |
|---|---|---|
| `query` | string | required |
| `limit` | int | `10` |

`query` is embedded with the corpus embedding model, then matched against the chunk vector index and
ordered by ascending distance.

**Returns**: a list of at most `limit` objects, each with `chunk_text` (the full chunk body),
`document_path` (corpus-relative path of the source file) and `entities`, a list of
`{name, type}` objects for the entities mentioned in that chunk. The similarity distance and the
chunk's character offsets are computed internally but not included in the tool's result.

**Ask**: "What do my notes say about the partnership review?"

### get_entity_tool

Get full entity record including attributes, mentions, and relations.

| Parameter | Type | Default |
|---|---|---|
| `name` | string | required |
| `type` | string | `null` (any type) |

`name` is matched against the canonical name exactly, not as a substring. Pass `type` to disambiguate
when the same name exists under two entity types.

**Returns**: an object with `id`, `name`, `type`, `attributes`, `mentions`, `outgoing_relations` and
`incoming_relations`. Each mention carries `surface_form`, `confidence`, `document` and `chunk_text`
truncated to 200 characters. Outgoing relations carry `predicate`, `object`, `object_type`,
`confidence` and `attributes`; incoming relations carry `subject` and `subject_type` in place of the
object fields. When no entity matches, the tool returns the string `Entity '<name>' not found.`
instead of an object.

**Ask**: "Tell me everything the graph knows about Sarah Chen."

### list_entities_tool

List entities, optionally filtered by type.

| Parameter | Type | Default |
|---|---|---|
| `type` | string | `null` (all types) |
| `limit` | int | `50` |

**Returns**: a list of at most `limit` objects, each with `id`, `name`, `type` and `attributes`,
ordered by name. Name substring filtering is available on the CLI's `kgmd entities` but is not
exposed by this tool.

**Ask**: "List the organizations in my graph."

### get_neighbors_tool

Get the subgraph around an entity up to a given depth.

| Parameter | Type | Default |
|---|---|---|
| `name` | string | required |
| `depth` | int | `1` |

Traversal is breadth-first and ignores edge direction, so a depth of 1 returns both the entities this
one points at and the entities that point at it.

**Returns**: an object with two keys. `nodes` is a list of `{name, type, attributes}` for the centre
and everything reached within `depth` hops. `edges` is a list of
`{source, target, predicate, confidence}` for every relation among those nodes, including edges
between two neighbours. An unknown `name` returns empty `nodes` and `edges` rather than an error.

**Ask**: "Who and what is connected to Acme Corp, two hops out?"

### find_path_tool

Find the shortest path between two entities.

| Parameter | Type | Default |
|---|---|---|
| `from_name` | string | required |
| `to_name` | string | required |
| `max_depth` | int | `5` |

The search runs over the undirected view of the graph, so it will traverse a relation backwards to
reach the target.

**Returns**: a list of `{source, target, predicate}` objects, one per hop, in order from `from_name`
to `to_name`. Each hop reports the direction the relation was actually stored in, which may be the
reverse of the direction you are walking. When either endpoint is unknown, no path exists, or the
shortest path is longer than `max_depth` hops, the tool returns the string
`No path found between '<from_name>' and '<to_name>'.`

**Ask**: "How is Brian Anderson connected to the digital transformation programme?"

### list_relations_tool

List relations with optional filters.

| Parameter | Type | Default |
|---|---|---|
| `predicate` | string | `null` (all predicates) |
| `subject` | string | `null` (all subjects) |
| `object` | string | `null` (all objects) |
| `limit` | int | `50` |

`subject` and `object` match canonical entity names exactly; `predicate` matches the stored predicate
exactly. Filters combine with AND.

**Returns**: a list of at most `limit` objects, each with `id`, `subject`, `subject_type`,
`predicate`, `object`, `object_type`, `confidence` and `attributes`.

**Ask**: "List the relations where Acme Corp is the subject."

### get_schema_tool

Get the current induced schema.

This tool takes no parameters.

**Returns**: an object with `id`, `created_at`, `llm_model`, `entity_type_count`,
`relation_type_count`, `notes`, and `schema` — the induced schema parsed from its stored YAML into
nested objects. The newest schema version wins. If no schema has been induced yet, the tool returns
the string `No schema has been induced yet.`

**Ask**: "What entity and relation types exist in this graph?"

## Credentials

Serving queries needs no API key.

Six of the seven tools only run SQL. `search` is the exception: it embeds the query string before
searching, using the same embedder the corpus was built with. The default backend is `fastembed`,
which runs the model locally, so it needs no credential either. If you set
`embedding.backend: litellm` in the corpus config, `search` makes an embedding API call and does need
that provider's key in the server process environment; the other six tools still do not.

No tool calls a chat model. `kgmd/mcp_server.py` imports from `kgmd.query`, `kgmd.db`, `kgmd.config`
and `kgmd.embed` — none of which reaches the completion path used by the build stages. The provider
key you needed for `kgmd build` is not needed to serve queries. See
[../reference/configuration.md](../reference/configuration.md) for the embedding keys.

## Limits

The server is read-only. It has no tool that ingests a file, runs extraction, resolves entities,
induces a schema, or writes any row; every tool issues `SELECT` statements and closes its connection.
Build the graph first with `kgmd build` from a shell, then let the assistant read it.

Consequences worth knowing before you wire this into a workflow:

- Editing a markdown file changes nothing the assistant sees until you re-run `kgmd build`. There is
  no watcher.
- An initialized-but-unbuilt corpus serves successfully and answers with empty results, not errors.
  `list_entities_tool` returns an empty list and `get_schema_tool` returns
  `No schema has been induced yet.`
- Builds take an exclusive lock on `.kgmd/build.lock`; the server does not, so queries during a build
  see whatever the build has committed so far.
- One corpus per server entry. To expose two corpora, add two entries with different names and
  different `cwd` values.
- The tools expose entities, relations and chunk text — the same surface as the CLI query commands in
  [../reference/cli.md](../reference/cli.md), minus writes.

Related pages: [../quickstart.md](../quickstart.md) to get a graph built,
[../examples/mcp-assistant.md](../examples/mcp-assistant.md) for a worked assistant session,
[../concepts.md](../concepts.md) for what entities and mentions are, and
[../guides/troubleshooting.md](../guides/troubleshooting.md) when a tool call fails.
