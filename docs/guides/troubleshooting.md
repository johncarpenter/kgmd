# Troubleshooting
> Applies to kgmd 0.1.x

For anyone whose build, query, or MCP server just failed. Each entry below quotes the literal text
kgmd emits, explains why it is emitted, and gives the fix. Errors are rendered as a single
`Error: <message>` line unless you pass `--debug`, so the quoted strings are what you actually see on
the terminal.

### A query command cannot find your corpus

**Symptom**: `No .kgmd directory found`

**Cause**: `find`, `entities`, `relations`, `entity`, `neighbors`, `path`, `schema`, `stats`, and
`reset` locate the corpus by walking upward from the current directory looking for a `.kgmd/`
directory, and give up at the filesystem root. Either the corpus was never initialized, or you are
outside it.

**Fix**: `cd` into the corpus (any subdirectory of it works, since the search walks upward) and retry.
If it was never initialized, run `kgmd init`, then `kgmd build`. To query a corpus from an unrelated
directory, skip the search entirely by pointing `--db` at its database file.

### A pipeline command refuses to run in the current directory

**Symptom**: `Not a kgmd corpus. Run 'kgmd init' first.`

**Cause**: `extract`, `resolve`, and `induce` do not search upward. They check for `.kgmd/` directly
inside the path argument, which defaults to `.`. `build` performs the same check and its message also
names the directory it looked in.

**Fix**: Run `kgmd init` in that directory, or pass the corpus root explicitly as the path argument —
for example `kgmd extract ../notes`. Note that a corpus root is where `.kgmd/` lives, not any
subdirectory of it.

### A command aborts before doing any work, naming a database path

**Symptom**: `Database not found:`

**Cause**: `stats` and `reset` require the database file to already exist. Either `--db` points at a
path that is not there, or `.kgmd/` exists without a `graph.db` inside it — which happens if the file
was deleted, or if `kgmd init` was never followed by a build.

**Fix**: Check the path in the message. If it is the corpus default, run `kgmd build` to create and
populate the database; `kgmd build` calls `init_db`, so a deleted `graph.db` is recreated without
re-running `kgmd init`. If the path came from `--db`, correct the argument.

### The MCP server exits on the first tool call

**Symptom**: `No kgmd database found at`

**Cause**: The server resolves its database from the working directory of the process that launched
it: `Path.cwd() / ".kgmd" / "graph.db"`. MCP clients usually start servers in their own working
directory, not in your corpus, so the lookup misses.

**Fix**: Set the `cwd` of the server entry in your client configuration to the corpus root. See
[mcp.md](./mcp.md) for a complete client configuration block.

### Every chunk fails during extraction and no entities appear

**Symptom**: `Extraction failed:`

**Cause**: The message is emitted once per failing chunk by the extraction stage, which catches all
exceptions per chunk so one bad call cannot abort the run. The text after the colon comes from
litellm, not from kgmd — a missing or rejected provider credential surfaces here as
`litellm.AuthenticationError`. kgmd never reads, prompts for, or stores credentials; litellm picks
them up from the environment.

**Fix**: Export the key your `llm.model` provider expects and retry. For the default
`openrouter/...` model that is `OPENROUTER_API_KEY`:

```bash
export OPENROUTER_API_KEY="sk-..."
kgmd extract .
```

Documents whose every chunk failed keep a `NULL` extraction watermark, so a corrected retry picks
them up with no extra flags. If the text after the colon is a rate-limit or timeout error instead,
lower `llm.concurrency` or raise `llm.timeout_seconds`.

### Any command fails immediately on a fresh Python install

**Symptom**: `enable_load_extension`

**Cause**: kgmd stores vectors in `sqlite-vec`, a loadable SQLite extension. Opening the database
calls `conn.enable_load_extension(True)`, and that method only exists when the interpreter's
`sqlite3` module was built against a SQLite compiled with extension loading enabled. Several
distributions — notably some Homebrew and Conda Python builds, and the stock macOS system Python —
ship without it, so the attribute is missing and you get an `AttributeError` naming it.

**Fix**: Use an interpreter with extension support. Python from python.org, `uv python install`, and
`pyenv`-built interpreters all work. Confirm before reinstalling kgmd:

```bash
python -c "import sqlite3; sqlite3.connect(':memory:').enable_load_extension(True)"
```

Silence means the interpreter is fine. Installation options are in
[../install.md](../install.md).

### A build refuses to embed after you changed the embedding model

**Symptom**: `Database was initialized with embedding model`

**Cause**: The embedding model and its vector width are fixed when the database is created — the
vector tables are declared with a literal dimension and the model id is written into the `kv` table.
`build` and `extract` compare `embedding.model` from config against that stored value and stop if
they differ, rather than mixing vectors from two models.

**Fix**: Either revert `embedding.model` to the value in the message, or commit to the change by
deleting the database and rebuilding, which is what the message itself advises:

```bash
rm -f .kgmd/graph.db .kgmd/graph.db-wal .kgmd/graph.db-shm
kgmd build .
```

Rebuilding re-runs extraction and re-spends the provider budget. See
[maintenance.md](./maintenance.md) for the full procedure.

### A second build fails while the first is still running

**Symptom**: `Another kgmd build process (PID`

**Cause**: `build`, `extract`, `resolve`, `induce`, and `reset` take an exclusive lock on
`.kgmd/build.lock` and write their PID into it. A second process that cannot take the lock reads that
PID, finds the process alive, and refuses rather than corrupting a half-written graph.

**Fix**: Wait for the first build, or stop it. Query commands take no lock, so `kgmd stats` and the
rest keep working while a build runs. A lock left behind by a killed process is normally reclaimed
automatically — the reclaim path triggers when the recorded PID is dead or unparseable — so manual
cleanup is only needed for an empty lock file. Confirm no build is actually running first:

```bash
rm -f .kgmd/build.lock
```

### A build refuses to run after you edited the ignore file

**Symptom**: `Ignore rules exclude every markdown file in the corpus`

**Cause**: Ingest prunes unconditionally — every `documents` row whose path is no longer in the
resolved file set is removed, which is how a deleted, renamed, or newly ignored file leaves the
graph. An over-broad `.kgmdignore` pattern, usually a bare `*`, resolves the file set to nothing, and
the prune would then delete the entire graph. So an empty file set against a non-empty `documents`
table is treated as a mistake rather than an instruction: the build raises before any write, and
nothing was removed.

**Fix**: Look at what the rules actually resolve to, correct the pattern, and re-run:

```bash
kgmd build --dry-run
```

A dry run is a read and the guard only protects writes, so in this state it exits 0 and simply
reports zero included files — that zero is the confirmation, not a second failure. The last matching
rule wins, so a `!` line placed after the offending pattern is often the shortest correction; the
syntax is in [../reference/configuration.md](../reference/configuration.md). If emptying the graph
really was the intent, `kgmd reset --hard` is the explicit way to ask for it — subject to the reset
bug described below.

### The provider returns something that is not the expected JSON

**Symptom**: `LLM call failed after`

**Cause**: Extraction and resolution demand strict JSON matching a Pydantic model. The call wrapper
strips markdown code fences, parses JSON, and validates; on a parse or validation failure it retries
up to `extraction.retry_on_parse_failure` times, appending a corrective instruction — a "your output
was truncated, produce something shorter" message when the JSON ended mid-structure, otherwise a
"valid JSON only, no prose" message. When every attempt fails it raises this error, which extraction
then reports per chunk as `Extraction failed:`.

**Fix**: Persistent failures almost always mean the model is a poor fit for structured output rather
than a transient fault. In order of effectiveness: switch `llm.model` to a model with reliable JSON
output; lower `chunking.max_chars` so responses fit comfortably inside the token limit; raise
`extraction.retry_on_parse_failure`. Note that raising `llm.max_tokens` may not help, because the
extraction stage applies its own lower internal default — see
[../reference/configuration.md](../reference/configuration.md). Count the `[FAIL]` lines in
`.kgmd/logs/build.log` to see how widespread the problem is.

### The build reports success but the graph is empty

**Symptom**: `No entities found.`

**Cause**: A build reaches "Build complete." even when every extraction call failed, because failures
are per-chunk warnings rather than fatal errors. Induction also returns quietly with zero types when
there are no entities, so `kgmd schema` reports that no schema has been induced yet. The other
possibility is that nothing was ingested at all: ingest only walks `*.md` files, subtracts everything
matched by `.kgmdignore`, skips every path with a dot-prefixed component, and honours
`corpus.include` if set.

**Fix**: Read the stage lines the build printed. If stage 1 reported zero new or updated documents,
the problem is ingest — check the file extensions, check `.kgmdignore`, check that the notes are not
inside a dot-prefixed directory, and check `corpus.include`. If documents and chunks exist but
entities do not, the problem is extraction: look for `Extraction failed:` on stderr and `[FAIL]`
lines in `.kgmd/logs/build.log`, then follow the credential and JSON entries above. `kgmd stats`
prints document, chunk, entity, and relation counts, which isolates the stage that produced nothing.

### A file you can see in the corpus is never indexed

**Symptom**: `excluded as a dot-path`

**Cause**: Three filters stand between a `*.md` file and the graph, in a fixed order.
`corpus.include`, if set, scopes the candidate set. `.kgmdignore` then subtracts, and `!` lines
re-add — the last matching rule wins, so a broad pattern further down the file overrides an earlier
exception. The dot-path rule is applied last and dominates: any path with a component starting with
`.` is dropped, and no pattern, negated or not, can re-admit it. The usual surprises are in the
patterns themselves — `*` never crosses a `/`, and a pattern with no `/` in it at all matches at any
depth, so `drafts` excludes `projects/drafts/` as well as `drafts/`.

**Fix**: Ask kgmd what it resolved rather than re-reading the patterns:

```bash
kgmd build --dry-run
```

The report lists every included path and counts what was dropped by `.kgmdignore` separately from
what was dropped by the dot-path rule, which tells you which of the two to edit; `--json` gives the
same data in a scriptable shape. Pattern syntax and precedence are in
[../reference/configuration.md](../reference/configuration.md), the flags in
[../reference/cli.md](../reference/cli.md). A dot-path exclusion cannot be worked around, so a file
under a dot-prefixed directory has to move. If the file was in the graph until recently, the
`Removed:` line a build prints accounts for it — ignoring, deleting, and renaming a file are one
state as far as ingest is concerned.

### A query cannot find an entity you know is in the notes

**Symptom**: `Entity '`

**Cause**: `kgmd entity` matches on the canonical name the extraction stage chose, not on the text in
your file, and the lookup is exact. Resolution may also have merged the mention into a differently
named entity. Names are also case- and punctuation-sensitive.

**Fix**: Find the real canonical name first, then query it:

```bash
kgmd entities --search "anderson"
kgmd entity "Brian Anderson"
```

`kgmd entities --search` matches substrings, and `kgmd find` searches chunk text semantically, which
finds the note even when you cannot guess the entity name. `kgmd neighbors` and `kgmd path` are
softer: an unknown name gives an empty result rather than an error.

### Reset exits with a SQLite transaction error and changes nothing

**Symptom**: `conn.execute("VACUUM")`

**Cause**: In 0.1.0 both `kgmd reset` and `kgmd reset --hard` issue their `DELETE` statements and then
run `VACUUM` on the same connection. SQLite refuses to vacuum inside the transaction those deletes
opened, so the command exits 1 with `Error: cannot VACUUM from within a transaction`. Because the
transaction is never committed, nothing is deleted — the reset is a no-op, not a partial wipe.

**Fix**: Delete the database file instead and rebuild. This is a stronger reset than either flag
would have been, since it also clears the vector tables and the recorded embedding model:

```bash
rm -f .kgmd/graph.db .kgmd/graph.db-wal .kgmd/graph.db-shm
kgmd build .
```

`.kgmd/config.yaml` and `.kgmd/prompts/` are untouched by this.

## Getting more detail

`--debug` is a group-level flag, so it goes before the subcommand:

```bash
kgmd --debug build .
```

Without it, an unexpected exception is caught by kgmd's exception hook and printed as a single
`Error: <message>` line before exiting 1. With it, the hook is not installed and Python prints the
full traceback — which is what you want when the message alone does not identify the failing stage,
and what you should attach to a bug report.

The other source of detail is `.kgmd/logs/build.log`. Extraction appends one line per provider
attempt, recording only outcome, model id, prompt and response character counts, and elapsed
seconds:

```text
[FAIL] model=openrouter/anthropic/claude-sonnet-4-5 prompt_chars=20 resp_chars=139 elapsed=0.26s
```

The counts are enough to distinguish a credential failure (every line `[FAIL]`, tiny `resp_chars`,
sub-second `elapsed`) from truncation (`[FAIL]` with `resp_chars` at the token ceiling) from a
timeout (`elapsed` at `llm.timeout_seconds`). Prompts, responses, note content, and credentials are
never written to it. Resolution and induction calls are not logged at all, so an unexplained failure
in those stages needs `--debug`. Log semantics and retention are covered in
[maintenance.md](./maintenance.md).
