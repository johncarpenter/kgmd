# Contract: library API

**Feature**: [../spec.md](../spec.md) | Modules: `kgmd/ignore.py` (new), `kgmd/ingest.py` (changed)

Public functions carry type hints; the connection and the config dict are passed as arguments, never
reached for. No module-level mutable state.

## `kgmd/ignore.py` — new leaf module

Imports stdlib only (`dataclasses`, `pathlib`, `re`). Imports nothing from `kgmd`, so the
constitution's one-way dependency direction is preserved: `ingest` → `ignore` → nothing.

```python
@dataclass(frozen=True)
class IgnoreRule:
    pattern: str
    regex: re.Pattern[str]
    negated: bool
    dir_only: bool
    line_number: int


def parse_ignore_rules(text: str) -> list[IgnoreRule]:
    """Parse .kgmdignore text into ordered rules. Comments and blanks yield nothing."""


def load_ignore_rules(root: Path) -> list[IgnoreRule]:
    """Read <root>/.kgmdignore. Returns [] if absent; raises if present and undecodable."""


def is_ignored(rel_path: str, rules: list[IgnoreRule]) -> bool:
    """True if rel_path (corpus-relative, '/' separators) is excluded.

    Every rule is tested against rel_path and each of its ancestor prefixes;
    the last matching rule decides. Empty rules -> False.
    """


DEFAULT_IGNORE_TEMPLATE: str  # every line a comment or blank


def write_default_ignore_file(path: Path) -> None:
    """Write the starter .kgmdignore. Never overwrites an existing file."""
```

**Guarantees**

- `is_ignored([], …)` is `False` for every path — an absent ignore file cannot change behavior.
- `parse_ignore_rules` never raises on content; any line is either a rule or skipped. Only I/O and
  decoding fail, and only in `load_ignore_rules`.
- Rule order is preserved exactly; rules are never sorted or deduplicated.
- `is_ignored` is pure and does not touch the filesystem, so it is unit-testable without `tmp_path`.
- `write_default_ignore_file` is a no-op when the target exists — a user's file is never clobbered.

## `kgmd/ingest.py` — changed

```python
@dataclass(frozen=True)
class FileScan:
    included: list[Path]   # absolute, sorted — will be indexed
    ignored: list[Path]    # absolute, sorted — excluded by .kgmdignore
    dotpath: list[Path]    # absolute, sorted — excluded by the dot-path rule


def scan_corpus_files(root: Path, config: dict) -> FileScan:
    """Resolve what the corpus would index.

    corpus.include scopes candidates, .kgmdignore subtracts (negations re-add),
    the dot-path rule is applied last and is not overridable.
    """


def prune_missing_documents(conn, kept_rel_paths: set[str]) -> dict:
    """Remove indexed documents whose path is absent from kept_rel_paths.

    Covers newly-ignored, deleted, and renamed files identically. Clears chunks,
    mentions, evidence-bound relations, both vector tables, and entities left with
    no mention and no relation. Raises if kept_rel_paths is empty while documents
    exist, before any write.

    Returns counts: documents_removed, chunks_removed, relations_removed,
    entities_removed, vectors_removed.
    """


def dry_run_report(conn, corpus_dir: Path, config: dict) -> dict:
    """The payload behind `kgmd build --dry-run`. Read-only; never writes.

    `conn` may be None when no database exists yet, in which case
    counts.would_remove is 0. Paths in the returned dict are corpus-relative
    POSIX strings, sorted — the same form stored in documents.path.
    """
```

**Unchanged signatures** — `find_markdown_files(root, include=None)`, `_is_dotpath(filepath, root)`,
`chunk_markdown`, `hash_content`, and `ingest_documents(conn, corpus_dir, config)` all keep their
current shape. `scan_corpus_files` composes the first two rather than replacing them, which is what
makes "no `.kgmdignore` behaves exactly as today" hold by construction.

**`ingest_documents` behavior change**: it calls `scan_corpus_files` instead of inlining the
discovery-and-dot-path filter, then calls `prune_missing_documents` with the resolved relative paths
before its insert/update loop. Its return dict gains the five removal keys; existing keys (`new`,
`updated`, `skipped`, `chunks_created`) keep their names and meanings, so both current call sites
(`kgmd/cli.py` `build` and `extract`) keep working unchanged.

Pruning runs before the insert/update loop so a rename is a removal plus an insert within one
transaction, never a window where both paths exist.

**Why `dry_run_report` is a library function rather than CLI code**: the repository has no
CLI-invocation test convention — `tests/test_mcp.py` tests "the query layer that backs the MCP
tool", and no test uses `click.testing.CliRunner`. Keeping the payload in `ingest.py` means the
preview's substance (resolved set, counts, would-remove) is testable the same way everything else
is, and `cli.py` stays the thin renderer that Principle III requires. The two genuinely CLI-level
guarantees — that a dry run creates no `graph.db`, and that `--json` without `--dry-run` fails — do
need `CliRunner`, and establishing that convention in `tests/test_cli.py` is a deliberate, scoped
addition rather than an accident.

## Error contract

| Condition | Raised by | Type |
|---|---|---|
| `.kgmdignore` present but undecodable | `load_ignore_rules` | `RuntimeError`, message names the file |
| resolved set empty while `documents` non-empty | `prune_missing_documents` | `RuntimeError`, before any write |

`RuntimeError` matches the house style for library-layer failures (`check_embedding_model`,
`build_lock` in `kgmd/db.py`). The CLI's exception hook renders it as a single `Error: <message>`
line; `--debug` shows the traceback.

The empty-set message must be quotable in `docs/guides/troubleshooting.md`:
`test_quoted_errors_exist_in_source` requires the single code span on each `**Symptom**:` line to
appear verbatim in `kgmd/**/*.py`. So the interpolated document count goes in a later fragment and
the leading fragment stays one contiguous string literal that the doc quotes exactly.

## Call graph after the change

```text
cli.build / cli.extract
    └── ingest.ingest_documents
            ├── ingest.scan_corpus_files
            │       ├── ingest.find_markdown_files      (corpus.include scoping, unchanged)
            │       ├── ignore.load_ignore_rules + is_ignored
            │       └── ingest._is_dotpath              (last, non-overridable)
            └── ingest.prune_missing_documents

cli.build --dry-run
    └── ingest.scan_corpus_files      (+ a read-only documents.path count; no writes)

cli.init
    └── ignore.write_default_ignore_file
```
