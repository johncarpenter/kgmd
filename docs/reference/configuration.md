# Configuration Reference
> Applies to kgmd 0.2.x

For operators tuning a corpus: this page lists every configuration key kgmd reads, where the files
live, how the two files are merged, and which pipeline stage consumes each setting. After reading it
you can change chunking, model routing, resolution strictness, and corpus scope with confidence
about what will actually take effect.

## Where configuration lives

kgmd reads YAML from at most two files.

| File | Scope | Created by |
|---|---|---|
| `.kgmd/config.yaml` inside the corpus | that corpus only | `kgmd init` |
| a per-user global file | every corpus on the machine | you, by hand |

`kgmd init` creates `.kgmd/` and writes `config.yaml` seeded with the complete set of built-in
defaults, so a fresh corpus starts with every key present and explicit. Running `kgmd init` again in
an already-initialized directory does not overwrite anything: it prints the existing config and
exits.

The global file is optional and is never created for you. Its location comes from `platformdirs`:

| Platform | Global config path |
|---|---|
| macOS | `~/Library/Application Support/kgmd/config.yaml` |
| Linux/BSD | `~/.config/kgmd/config.yaml` (honours `XDG_CONFIG_HOME`) |
| Windows | `%LOCALAPPDATA%\kgmd\kgmd\config.yaml` (the doubled segment is correct) |

The macOS and Linux paths were confirmed by resolving `platformdirs` on those platforms. The Windows
path is derived from the `platformdirs` source rather than executed on Windows: `user_config_dir`
returns `user_data_dir`, which joins `%LOCALAPPDATA%` with the app author and then the app name, and
kgmd passes no author — hence `kgmd\kgmd`. Treat the Windows row as unconfirmed until someone
verifies it on a Windows machine.

Configuration is loaded by the commands that run pipeline stages or need an embedder: `kgmd build`,
`kgmd extract`, `kgmd resolve`, `kgmd induce`, and `kgmd find`, which embeds its query string. The
remaining query commands read only the database and ignore configuration entirely.

`kgmd build` accepts a `--config` option, but the value is not consulted: the build always loads
the corpus directory's own `.kgmd/config.yaml`. To point a build at different settings, edit that
file.

## Precedence

Three layers are combined, later layers winning:

1. built-in defaults compiled into kgmd
2. the global config file, if it exists
3. the corpus `.kgmd/config.yaml`, if it exists

The combination is a recursive merge, not a replacement. Each layer is walked key by key; when both
sides hold a mapping the merge descends into it, and only leaf values are overwritten. Writing one
key of a section in the corpus file therefore leaves that section's other keys at whatever the lower
layers set. A section you omit entirely still contributes all of its defaults.

Worked example. The global file sets two keys, `llm.model` and `chunking.max_chars`. The corpus file
sets one key, `chunking.max_chars`, and mentions nothing else. The effective configuration is:

| Key | Built-in default | Global file | Corpus file | Effective |
|---|---|---|---|---|
| `llm.model` | `openrouter/anthropic/claude-sonnet-4-5` | `openrouter/openai/gpt-4o-mini` | not set | `openrouter/openai/gpt-4o-mini` |
| `chunking.max_chars` | `4000` | `6000` | `2500` | `2500` |
| `chunking.overlap_chars` | `200` | not set | not set | `200` |
| `chunking.split_on` | `paragraph` | not set | not set | `paragraph` |

The last two rows are the point: the corpus file wrote a sibling key inside `chunking`, and the rest
of the section survived untouched.

## Settings

Nineteen keys, addressed here by their dotted path. In YAML the first segment is the top-level
mapping and the second is the key inside it.

| Key | Default | Accepted values | Effect |
|---|---|---|---|
| `corpus.include` | unset (`null`) | list of paths relative to the corpus root, each a directory or an `.md` file | Restricts ingestion to those paths. Entries are literal paths, not globs: `notes/*.md` matches nothing and fails silently. Unset means every `.md` file under the corpus root. Paths whose components begin with a dot are always skipped, so `.kgmd/` never ingests itself. This key scopes the directory walk; [`.kgmdignore`](#the-kgmdignore-file) subtracts from whatever it selects. |
| `embedding.backend` | `fastembed` | `fastembed`, `litellm` | Selects the embedder. `fastembed` runs the model locally and needs no credential; `litellm` routes embedding calls to a hosted provider. Any other value falls back to `fastembed`. |
| `embedding.model` | `BAAI/bge-small-en-v1.5` | a model id the chosen backend understands | Model used to embed chunks and entity mentions. The id is recorded in the database at first build and is fixed for the life of the corpus; changing it later aborts the build. See the [maintenance guide](../guides/maintenance.md). |
| `llm.model` | `openrouter/anthropic/claude-sonnet-4-5` | any litellm-routable model id | Model used for extraction, resolution cluster verification, and schema induction. |
| `llm.temperature` | `0.0` | float, provider-dependent range | Sampling temperature for the extraction stage. Resolution and induction pin `0.0` regardless of this key. Extraction is only reproducible at `0.0`, which is what the project relies on. |
| `llm.max_tokens` | `16384` | int > 0 | Response token ceiling for extraction calls. Note the divergence: the config default is `16384`, but the extraction stage and the litellm wrapper each apply their own internal default of `4096` when the key is absent from the config they receive, and resolution and induction hard-code `4096` and ignore this key. Raising it only affects extraction. |
| `llm.timeout_seconds` | `120` | int > 0 | Per-request timeout handed to litellm by the extraction stage. Resolution and induction use the wrapper's own `120`. |
| `llm.concurrency` | `4` | int >= 1 | Worker threads extracting chunks in parallel. Chunks are submitted to one pool, so this is the ceiling on in-flight LLM requests during extraction. |
| `chunking.max_chars` | `4000` | int > 0 | Upper bound on chunk length. Paragraph and heading splitting merge adjacent segments until adding the next one would exceed it; fixed splitting uses it as the window size. |
| `chunking.overlap_chars` | `200` | int >= 0 | Characters each fixed-size window repeats from the previous one. Only consulted when `chunking.split_on` is `fixed`. |
| `chunking.split_on` | `paragraph` | `paragraph`, `heading`, `fixed` | Segmentation strategy: blank-line-separated paragraphs, markdown headings of any level, or fixed-size overlapping windows. An unrecognized value behaves as `paragraph`. |
| `extraction.max_entities_per_chunk` | `30` | int > 0 | **Accepted but currently has no effect.** No module reads the key; the number of entities returned per chunk is bounded only by the extraction prompt and the model. |
| `extraction.max_relations_per_chunk` | `30` | int > 0 | **Accepted but currently has no effect.** No module reads the key; the number of relations returned per chunk is bounded only by the extraction prompt and the model. |
| `extraction.retry_on_parse_failure` | `2` | int >= 0 | Extra attempts when a model reply fails JSON decoding or schema validation. Total attempts are this value plus one. Only extraction passes it through; resolution verification uses the wrapper's own `2`. |
| `resolution.similarity_threshold` | `0.85` | float between 0 and 1 | Cosine similarity at or above which two mentions of the same entity type are unioned into one candidate cluster. Lower values merge more aggressively. |
| `resolution.llm_verify_clusters` | `true` | bool | When true, each candidate cluster is sent to the model, which may split it. When false, every cluster is merged as-is under its first surface form. |
| `resolution.max_cluster_size` | `10` | int >= 2 | Clusters larger than this are recursively re-clustered with the threshold raised by `0.05` each round, which splits loose groups instead of collapsing them. |
| `induction.include_attribute_summary` | `true` | bool | **Accepted but currently has no effect.** No module reads the key; what the induced schema summarizes is decided entirely by the induction prompt. |
| `induction.hierarchy_depth` | `3` | int >= 1 | Interpolated into the induction prompt as the maximum depth of the entity type hierarchy the model may produce. |

## The `.kgmdignore` file

Exclusions are not a config key. They live in a `.kgmdignore` file at the **corpus root** — beside
your markdown, not inside `.kgmd/` — so the file can sit in version control with the notes it
describes. `kgmd init` writes a starter copy whose every line is a comment, which is why a fresh
corpus indexes exactly what it would have without one.

This matters for cost, not tidiness. Every indexed file is chunked and each chunk is one model call,
so a vendored documentation tree or a folder of boilerplate templates is a repeated charge that buys
nothing and fills entity resolution with junk mentions.

```text
# skip archived notes
archive/
drafts/

# skip generated or boilerplate files
**/CHANGELOG.md
*-template.md

# but keep this one
!archive/2024-decisions.md
```

A missing file means no exclusions, and behaves exactly as kgmd did before the file existed. A file
that is present but unreadable or not UTF-8 is an error rather than a silent skip, because treating
it as absent would index everything you meant to exclude. Only the corpus-root file is read; a
`.kgmdignore` in a subdirectory is ignored. The file is re-read on every run, so editing it takes
effect on the next `kgmd build` with no invalidation step.

### Syntax

Patterns match the path relative to the corpus root, always with `/` separators, and matching is
case-sensitive regardless of what the filesystem does.

| Construct | Meaning |
|---|---|
| `# comment` | ignored, as are blank lines and surrounding whitespace |
| `*` | any run of characters, never crossing `/` |
| `?` | exactly one character, never `/` |
| `**` | any number of path segments; `a/**/b` also matches `a/b` |
| trailing `/` | directory-only: that directory and everything beneath it |
| leading `/` | anchored at the corpus root |
| any interior `/` | anchored at the corpus root |
| no `/` anywhere | matches at any depth |
| leading `!` | negation — re-includes a path an earlier rule excluded |

A pattern without a trailing `/` matches a file with that path *and* anything beneath a directory
with that path, so `archive` and `archive/` differ only in whether a file literally named `archive`
matches.

Character classes (`[a-z]`) and backslash escapes are **not** supported. A pattern using them is
matched literally, so it excludes nothing rather than excluding too much.

### Precedence

Fixed, and not configurable:

1. `corpus.include` scopes the candidate set.
2. `.kgmdignore` rules are evaluated in file order and **the last matching rule wins**.
3. The dot-path rule is applied last and dominates.

Each candidate file is tested against every rule, both on its own path and on each of its ancestor
directories — which is what lets a directory rule cover a whole subtree. A path with any
dot-prefixed component (`.kgmd/`, `.git/`, `.claude/`) is excluded after all rules have been
evaluated, and no pattern can re-admit it: `!.kgmd/notes.md` has no effect.

### One difference from `.gitignore`

git cannot re-include a file whose parent directory is excluded. `.kgmdignore` can. In the example
above, `archive/` excludes the directory and `!archive/2024-decisions.md` still brings that one file
back, because rules are evaluated per file rather than by skipping directories outright. If you are
carrying patterns over from a `.gitignore`, this is the one place the two disagree.

### Seeing what a rule does

`kgmd build --dry-run` prints the resolved file set and the counts excluded by `.kgmdignore` and by
the dot-path rule, without writing anything or calling a model. Use it before a build rather than
inferring rules from a bill. See the [CLI reference](./cli.md).

A file that becomes excluded is also **removed** from an existing graph on the next
`kgmd build` or `kgmd extract`, along with everything derived from it. As a guard, ignore rules that
resolve to an empty file set abort the build instead of emptying the graph. Both behaviours are
described in the [maintenance guide](../guides/maintenance.md).

## Full example

A corpus `.kgmd/config.yaml` holding all nineteen keys at their defaults, which is what `kgmd init`
writes:

```yaml
corpus:
  # null means every .md file under the corpus root
  include: null
embedding:
  # fastembed runs locally; litellm calls a hosted provider
  backend: fastembed
  # fixed once the corpus is built - changing it requires a rebuild
  model: BAAI/bge-small-en-v1.5
llm:
  model: openrouter/anthropic/claude-sonnet-4-5
  # keep at 0.0 for reproducible extraction
  temperature: 0.0
  # extraction honours this; other stages use 4096
  max_tokens: 16384
  timeout_seconds: 120
  # parallel extraction workers
  concurrency: 4
chunking:
  max_chars: 4000
  # only used when split_on is fixed
  overlap_chars: 200
  # paragraph | heading | fixed
  split_on: paragraph
extraction:
  # accepted, inert
  max_entities_per_chunk: 30
  # accepted, inert
  max_relations_per_chunk: 30
  retry_on_parse_failure: 2
resolution:
  similarity_threshold: 0.85
  llm_verify_clusters: true
  max_cluster_size: 10
induction:
  # accepted, inert
  include_attribute_summary: true
  hierarchy_depth: 3
```

Deleting keys is safe: anything absent falls back through the precedence chain to the built-in
default.

## Which stages read what

The pipeline stages are described in [concepts](../concepts.md); this is the mapping from config
section to the stage that consumes it.

| Section | Stage | Module |
|---|---|---|
| corpus | ingest — file discovery | `kgmd/ingest.py` |
| chunking | ingest — chunk construction | `kgmd/ingest.py` |
| embedding | embedding of chunks and mentions, and query embedding for search | `kgmd/embed.py` |
| llm | extraction, and model selection for resolution and induction | `kgmd/extract.py`, `kgmd/llm.py` |
| extraction | extraction retry behaviour | `kgmd/extract.py` |
| resolution | entity resolution | `kgmd/resolve.py` |
| induction | schema induction | `kgmd/induce.py` |

Configuration changes take effect on the next run of the affected stage. Chunking changes only
re-chunk documents whose content changed, because ingestion skips unchanged files by content hash;
to apply new chunking to the whole corpus, rebuild it as described in the
[maintenance guide](../guides/maintenance.md). Command-level details for the flags mentioned here
are in the [CLI reference](./cli.md).
