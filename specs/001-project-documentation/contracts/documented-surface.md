# Contract: Documented Surface Inventory

**Feature**: [../spec.md](../spec.md) | **Plan**: [../plan.md](../plan.md) | **Date**: 2026-08-28

This is the contract between the tool's real surface and the documentation set. It is **derived, not
authored**: every row below was introspected from `kgmd` 0.1.0 in the project venv. The
implementation MUST re-derive it at test time rather than trusting this file — this snapshot exists
so a reviewer can see the target, and so drift in the snapshot itself is obvious.

## Derivation (reference implementation)

```python
# Commands, parameters, global options, export formats — via Click's own tree
from kgmd.cli import main
commands = sorted(main.commands)                      # 16
global_opts = [o for p in main.params for o in p.opts]  # ['--debug']
params = {n: [p for p in c.params] for n, c in main.commands.items()}  # 49 total
formats = list(main.commands["export"].params[0].type.choices)  # 3

# Configuration keys — recursive flatten to dotted paths
from kgmd.config import DEFAULT_CONFIG                # 19 leaves

# MCP tools — AST, to avoid importing fastembed transitively (see research R-003)
import ast, pathlib
tree = ast.parse(pathlib.Path("kgmd/mcp_server.py").read_text())
tools = [n.name for n in tree.body
         if isinstance(n, ast.FunctionDef)
         for d in n.decorator_list
         if isinstance((f := d.func if isinstance(d, ast.Call) else d), ast.Attribute)
         and f.attr == "tool"]                        # 7
```

## 1. Commands — 16, all MUST appear as `### <name>` in `docs/reference/cli.md`

| Command | Positional arguments | Options | `--json`? | Currently in README |
|---|---|---|---|---|
| `init` | — | `--path` | no | yes |
| `stats` | — | `--db`, `--json` | **yes** | yes |
| `build` | `path` | `--db`, `--config` | no | yes |
| `extract` | `path` | `--db`, `--force` | no | **NO** |
| `resolve` | `path` | `--db` | no | **NO** |
| `induce` | `path` | `--db` | no | **NO** |
| `find` | `query` | `--limit/-n`, `--db`, `--json` | **yes** | yes |
| `entities` | — | `--type`, `--limit/-n`, `--search`, `--db`, `--json` | **yes** | yes |
| `relations` | — | `--predicate`, `--subject`, `--object`, `--limit/-n`, `--db`, `--json` | **yes** | yes |
| `entity` | `name` | `--type`, `--db`, `--json` | **yes** | yes |
| `neighbors` | `name` | `--depth/-d`, `--type`, `--db`, `--json` | **yes** | yes |
| `path` | `from_name`, `to_name` | `--max-depth`, `--db`, `--json` | **yes** | yes |
| `schema` | — | `--db`, `--json` | **yes** | yes |
| `export` | — | `--format` (required), `--output/-o`, `--db` | no | yes |
| `reset` | — | `--hard`, `--yes` | no | **NO** |
| `mcp` | — | — | no | yes |

Totals: 9 positional arguments, 40 options, 49 parameters. Every one MUST appear as an inline code
span inside its command's section.

**Global**: `--debug` on the `kgmd` group itself; MUST be documented once in
`docs/reference/cli.md` (FR-013). It changes error rendering from a one-line `Error: …` to a full
traceback.

**Structured output**: exactly 8 commands (`stats`, `find`, `entities`, `relations`, `entity`,
`neighbors`, `path`, `schema`). Each entry MUST show the human form and the `--json` form (FR-014).

## 2. Configuration keys — 19, all MUST appear in `docs/reference/configuration.md`

| Key | Default | Accepted values | Status |
|---|---|---|---|
| `corpus.include` | `None` | list of corpus-relative paths, or unset for all | active — **absent from README** |
| `embedding.backend` | `fastembed` | `fastembed`, `litellm` | active |
| `embedding.model` | `BAAI/bge-small-en-v1.5` | backend-dependent model id | active, **immutable per corpus** |
| `llm.model` | `openrouter/anthropic/claude-sonnet-4-5` | any litellm-routable model id | active |
| `llm.temperature` | `0.0` | float ≥ 0 | active — raising it breaks determinism (Principle II) |
| `llm.max_tokens` | `16384` | int > 0 | active, **divergent**: extraction applies its own lower internal default |
| `llm.timeout_seconds` | `120` | int > 0 | active |
| `llm.concurrency` | `4` | int ≥ 1 | active — **absent from README** |
| `chunking.max_chars` | `4000` | int > 0 | active |
| `chunking.overlap_chars` | `200` | int ≥ 0 | active |
| `chunking.split_on` | `paragraph` | `paragraph`, `heading`, `fixed` | active |
| `extraction.max_entities_per_chunk` | `30` | int > 0 | **INERT — no effect** |
| `extraction.max_relations_per_chunk` | `30` | int > 0 | **INERT — no effect** |
| `extraction.retry_on_parse_failure` | `2` | int ≥ 0 | active |
| `resolution.similarity_threshold` | `0.85` | float 0–1 | active |
| `resolution.llm_verify_clusters` | `true` | bool | active |
| `resolution.max_cluster_size` | `10` | int ≥ 2 | active |
| `induction.include_attribute_summary` | `true` | bool | **INERT — no effect** |
| `induction.hierarchy_depth` | `3` | int ≥ 1 | active |

**Precedence** (MUST be documented with a worked merge example, FR-016):
`DEFAULT_CONFIG` → global config → corpus `.kgmd/config.yaml`, deep-merged per key.

**Global config path** (source-verified, R-010):

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/kgmd/config.yaml` |
| Linux/BSD | `~/.config/kgmd/config.yaml` (honours `XDG_CONFIG_HOME`) |
| Windows | `%LOCALAPPDATA%\kgmd\kgmd\config.yaml` — doubled segment is correct; confirm on Windows before release |

## 3. MCP tools — 7, all MUST appear in `docs/guides/mcp.md`

Names are **as registered**, verified via `asyncio.run(mcp.list_tools())`:

| Registered name | Parameters | Returns | README claims |
|---|---|---|---|
| `search` | `query: str`, `limit: int = 10` | list of chunks with entities | `search` — correct |
| `get_entity_tool` | `name: str`, `type: str \| None = None` | entity record or message | `get_entity` — **WRONG** |
| `list_entities_tool` | `type: str \| None = None`, `limit: int = 50` | list of entities | `list_entities` — **WRONG** |
| `get_neighbors_tool` | `name: str`, `depth: int = 1` | subgraph | `get_neighbors` — **WRONG** |
| `find_path_tool` | `from_name: str`, `to_name: str`, `max_depth: int = 5` | path or message | `find_path` — **WRONG** |
| `list_relations_tool` | `predicate`, `subject`, `object`, `limit` (all optional) | list of relations | `list_relations` — **WRONG** |
| `get_schema_tool` | — | current induced schema or message | `get_schema` — **WRONG** |

Contract for the docs: document the registered names. Do not rename (see plan.md Complexity
Tracking). The page SHOULD note that names carry a `_tool` suffix for historical reasons so readers
who saw the old README table are not left confused.

**Client configuration** MUST be documented with a copy-pasteable block and the per-platform config
file location (FR-018). The server resolves its database from the process working directory
(`Path.cwd() / ".kgmd" / "graph.db"`), so the client's `cwd` setting is load-bearing and MUST be
called out.

## 4. Export formats — 3, all MUST appear in `docs/reference/export.md`

| `--format` value | Contains | Consuming tool |
|---|---|---|
| `jsonld` | JSON-LD with schema.org context | generic linked-data tooling |
| `cypher` | `CREATE` statements | Neo4j |
| `graphml` | GraphML | Gephi, yEd, NetworkX |

Output goes to stdout unless `--output/-o` is given; both MUST be shown.

## Contract tests (bidirectional, offline)

| Test | Assertion | Requirement |
|---|---|---|
| `test_all_commands_documented` | `introspected_commands == documented_headings` (set equality) | FR-012, SC-002 |
| `test_all_parameters_documented` | every parameter appears in its command's section | FR-012 |
| `test_global_option_documented` | `--debug` documented | FR-013 |
| `test_structured_output_parity` | `as_json` set == documented-`--json` set | FR-014 |
| `test_all_config_keys_documented` | `flatten(DEFAULT_CONFIG) == documented_keys` | FR-015, SC-002 |
| `test_inert_keys_marked` | the 3 inert keys carry the inert marker | FR-017 |
| `test_all_mcp_tools_documented` | AST tool names == documented names | FR-018, SC-002 |
| `test_all_export_formats_documented` | Click choices == documented formats | FR-019 |
| `test_no_phantom_entries` | no documented identifier is absent from the code | FR-041 |

Set equality in both directions is the point: a one-directional "everything real is documented"
check would still have passed the README's six phantom tool names.
