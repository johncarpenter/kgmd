# Contract: Page Conventions

**Feature**: [../spec.md](../spec.md) | **Plan**: [../plan.md](../plan.md) | **Date**: 2026-08-28

The structural contract every page in `docs/` MUST satisfy. These conventions exist so that
`tests/test_docs.py` can parse pages without a markdown library — plain `re` over lines is enough,
which keeps the check dependency-free per Constitution "no new deps".

## C-1: Page skeleton

Every `docs/**/*.md` file MUST begin exactly like this:

```markdown
# <Page Title>
> Applies to kgmd 0.1.x

<one-paragraph statement of who this page is for and what they will be able to do>
```

- Line 1: single `# ` H1. No other H1 in the file.
- Line 2: version stamp, matching `^> Applies to kgmd (\d+)\.(\d+)\.x$`, whose major/minor MUST equal
  `kgmd.__version__`'s major/minor.
- Line 3: blank.
- Line 4+: audience paragraph before any other heading.

**Rationale**: a fixed prologue makes stamp checking a two-line read, and gives every reader landing
mid-set the version and audience immediately.

## C-2: Command reference entries (`docs/reference/cli.md`)

One section per command, heading exactly `### <command-name>` with no backticks or prefix, so the
heading text is the identifier the test compares:

```markdown
### neighbors

Subgraph traversal around an entity.

**Usage**: `kgmd neighbors NAME [OPTIONS]`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `NAME` | argument | required | Entity to traverse from. |
| `--depth` / `-d` | int | `1` | Traversal depth. |
| `--type` | string | all types | Restrict to one entity type. |
| `--db` | path | corpus database | Alternate database path. |
| `--json` | flag | off | Structured output. |

```bash
kgmd neighbors "Brian Anderson" --depth 2
```

**Structured output**:

```bash
kgmd neighbors "Brian Anderson" --depth 2 --json
```
```

Rules:
- Every parameter from the inventory MUST appear as an inline code span in the table.
- Short and long forms go in one cell as `` `--depth` / `-d` ``.
- Commands with `as_json` MUST carry a `**Structured output**:` block (this exact literal is what the
  parity test greps).
- At least one `bash` example block per command.

## C-3: Configuration entries (`docs/reference/configuration.md`)

One table row per key, dotted identifier in an inline code span in the first column:

```markdown
| Key | Default | Accepted values | Effect |
|---|---|---|---|
| `resolution.similarity_threshold` | `0.85` | float 0–1 | Cosine similarity above which two mentions are clustered as candidate duplicates. |
| `extraction.max_entities_per_chunk` | `30` | int > 0 | **Accepted but currently has no effect.** |
```

Rules:
- Identifier MUST be the full dotted path, matching the flattened `DEFAULT_CONFIG` key exactly.
- The three inert keys MUST contain the literal string
  `Accepted but currently has no effect` (the marker the test greps).
- `llm.max_tokens` MUST carry a note that the extraction stage applies a lower internal default.

## C-4: MCP tool entries (`docs/guides/mcp.md`)

One section per tool, heading exactly `### <registered_name>` — including the `_tool` suffix:

```markdown
### get_neighbors_tool

Returns the subgraph around an entity.

| Parameter | Type | Default |
|---|---|---|
| `name` | string | required |
| `depth` | int | `1` |

**Returns**: subgraph object with `nodes` and `edges` (verified against `kgmd/query.py` during
implementation — there is no `center` key).
```

Rules:
- Heading text MUST match the registered name byte-for-byte; the test compares against AST-derived
  names, so `get_neighbors` would fail.
- The page MUST include one note explaining the `_tool` suffix and one warning that the server
  resolves its database from the client's working directory.

## C-5: Troubleshooting entries (`docs/guides/troubleshooting.md`)

```markdown
### Build fails immediately with a database error

**Symptom**: `Database not found:`

**Cause**: The command was run outside an initialized corpus, or `--db` pointed at a path that does
not exist yet.

**Fix**: Run `kgmd init` in the corpus directory, then `kgmd build`.
```

Rules:
- Exactly one `**Symptom**:` line per entry, containing exactly one inline code span.
- The code span MUST be the literal source text up to the first interpolated value (R-007). For
  `f"Database not found: {db_path}"` quote `Database not found:` — not the whole f-string, not a
  paraphrase.
- The quoted text MUST exist verbatim in some `kgmd/**/*.py`; the test greps for it.
- `**Cause**:` and `**Fix**:` lines are mandatory.

## C-6: Walkthrough skeleton (`docs/examples/*.md`)

Required sections in this order: `## Goal`, `## Prerequisites`, `## Corpus`, `## Steps`,
`## Expected output`, `## Limitations`.

Rules:
- `## Prerequisites` MUST state explicitly whether a git checkout is required (fixtures are not in
  the wheel).
- `## Corpus` MUST reference `tests/fixtures/` or the quickstart's inline mini-corpus. Never a new
  copy of the notes.
- Exact entity/relation counts are permitted **only** on the `tests/fixtures/` path, where the test
  suite pins them. On the inline-corpus path describe output shape, not counts — LLM output is
  nondeterministic.
- Credentials appear only as `export OPENROUTER_API_KEY="sk-..."` style placeholders. Any string
  matching a plausible real key fails the suite.

## C-7: Links

- Internal links MUST be relative paths (`../reference/cli.md`, not `/docs/reference/cli.md`), so
  they resolve both on GitHub and in local editors.
- Every internal target MUST exist on disk.
- Every page MUST be reachable from `docs/README.md` within two links.
- External links are permitted and are never fetched by the test.
- References to repository files (e.g. `tests/fixtures/acme_corp.md`) MUST use paths that resolve
  from the repository root.

## C-8: Concept vocabulary

The six terms — document, chunk, entity, mention, relation, induced schema — are defined once, in
`docs/concepts.md`, each under a `### <term>` heading. Other pages link to those headings instead of
restating definitions (FR-021).

## C-9: Prohibited content

- No absolute filesystem paths belonging to a developer's machine (`/Users/...`, `C:\Users\...`).
- No real or realistic credentials (FR-035).
- No claims about behaviour that contradicts the inventory in
  [documented-surface.md](./documented-surface.md).
- No restatement of constitutional rules in `docs/contributing/` — link to
  `.specify/memory/constitution.md` instead (FR-038), so governance cannot fork.
- No "coming soon" or "TODO" placeholders; an unwritten page is not shipped.

## Enforcement summary

| Convention | Enforced by | Failure mode |
|---|---|---|
| C-1 skeleton and stamp | `test_page_skeleton`, `test_version_stamps` | missing/stale stamp fails suite |
| C-2 command entries | `test_all_commands_documented`, `test_all_parameters_documented`, `test_structured_output_parity` | added flag with no doc fails suite |
| C-3 config entries | `test_all_config_keys_documented`, `test_inert_keys_marked` | new key with no doc fails suite |
| C-4 tool entries | `test_all_mcp_tools_documented` | renamed tool with stale doc fails suite |
| C-5 troubleshooting | `test_quoted_errors_exist_in_source` | reworded error message fails suite |
| C-6 walkthroughs | `test_walkthrough_sections`, `test_no_credential_shaped_strings`, `test_fixture_references_exist` | missing section or leaked key fails suite |
| C-7 links | `test_internal_links_resolve`, `test_two_link_reachability` | moved page fails suite |
| C-8 vocabulary | `test_concept_terms_defined` | undefined term fails suite |
| C-9 prohibited content | `test_no_absolute_paths`, `test_no_credential_shaped_strings`; rest reviewer-owned | leaked path fails suite |
