# Contract: `kgmd build --dry-run`

**Feature**: [../spec.md](../spec.md) | Satisfies FR-017, FR-018

## Signature

```text
kgmd build [OPTIONS] [PATH]

  PATH          argument   default "."     Corpus directory; must exist.
  --db          path       <PATH>/.kgmd/graph.db
  --config      path       —               Accepted but ignored (pre-existing).
  --dry-run     flag       off             Report the resolved file set and exit. NEW
  --json        flag       off             Machine-readable output. Requires --dry-run. NEW
  --help        flag       off
```

## Behavior

`--dry-run` resolves the file set and reports it. It performs **no** writes:

- no `documents`, `chunks`, `entity_mentions`, `relations`, `entities`, or vector rows created,
  updated, or deleted
- no language-model call, no embedding call
- no `graph.db` created — the dry-run branch runs **before** `init_db`, so a dry run against a corpus
  that has never been built leaves the filesystem untouched apart from reads
- no build lock taken (it is a read, consistent with query commands)

Removal counts are computed by comparing recorded `documents.path` values against the resolved set.
When `graph.db` does not exist, `would_remove` is `0`.

`--json` without `--dry-run` fails: `--json requires --dry-run.` Exit 1, nothing else printed. This
is deliberate — the alternative, `--json` implying `--dry-run`, would make `kgmd build --json`
silently not build.

## Human output

```text
$ kgmd build --dry-run
Resolved 3 files to index (2 excluded by .kgmdignore, 1 excluded as a dot-path).
  notes/today.md
  notes/projects/atlas.md
  archive/2024-decisions.md
Already indexed but no longer in the corpus: 1 document would be removed.
```

Ordering is the sorted corpus-relative path order, identical to ingest order. With no `.kgmdignore`
present, the exclusion clause names only the dot-path count.

## Structured output

`kgmd build --dry-run --json` writes one JSON object to stdout and nothing else:

```json
{
  "included": ["archive/2024-decisions.md", "notes/projects/atlas.md", "notes/today.md"],
  "ignored": ["archive/old.md", "drafts/idea.md"],
  "dotpath": [".kgmd/notes.md"],
  "counts": {
    "included": 3,
    "ignored": 2,
    "dotpath": 1,
    "would_remove": 1
  }
}
```

| Field | Type | Meaning |
|---|---|---|
| `included` | `list[str]` | corpus-relative paths that would be indexed, sorted |
| `ignored` | `list[str]` | paths excluded by `.kgmdignore`, sorted |
| `dotpath` | `list[str]` | paths excluded by the dot-path rule, sorted |
| `counts.would_remove` | `int` | indexed documents whose path is absent from `included` |

Every path is corpus-relative POSIX, matching the form stored in `documents.path`. Absolute paths
never appear, so output is stable across machines and safe to commit in a test fixture.

## Errors

| Condition | Behavior |
|---|---|
| `PATH` has no `.kgmd/` | `Not a kgmd corpus (no .kgmd/ in <path>). Run 'kgmd init' first.` (pre-existing) |
| `--json` without `--dry-run` | `--json requires --dry-run.`, exit 1 |
| `.kgmdignore` unreadable or not UTF-8 | error naming the file, exit 1, no output |
| resolved set empty, graph non-empty | dry run **reports** it and exits 0; it is not a write, so the FR-015 guard does not fire here. A real build fails. |

## Documentation gate consequences

Both are obligations, not options — `tests/test_docs.py` enforces them:

- `test_all_parameters_documented` requires `` `--dry-run` `` and `` `--json` `` as inline code spans
  in the `### build` section of `docs/reference/cli.md`.
- `test_structured_output_parity` compares the set of commands documented with a
  `**Structured output**:` block against the set of commands having an `as_json` parameter. Adding
  `--json` to `build` puts it in the second set, so the block becomes mandatory.

## Non-goals

- No MCP tool. The preview answers a filesystem-and-config question about work not yet done, for an
  operator about to spend money; MCP tools read committed graph state for an assistant. Stated here
  because Principle III requires a reason when new capability reaches only one surface.
- No `kgmd/query.py` function. The resolved file set is not graph state; `query.py` remains the sole
  read layer for the graph, and discovery stays in `ingest.py`.
