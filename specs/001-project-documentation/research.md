# Phase 0 Research: Project Documentation Set

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-28

All Technical Context entries were resolvable from the repository; **no NEEDS CLARIFICATION markers
remain**. Every measurement below was produced by executing against the repository, not estimated.

## Measured baseline

Introspected from the installed package (`.venv/bin/python`, `kgmd` 0.1.0):

| Surface | Actual | Documented in `README.md` today | Gap |
|---|---|---|---|
| CLI commands | **16** | 12 | `extract`, `resolve`, `induce`, `reset` absent |
| Global options | 1 (`--debug`) | 0 | absent |
| Configuration keys | **19** | 17 | `corpus.include`, `llm.concurrency` absent |
| MCP tools | **7** | 7 listed, **6 names wrong** | see R-002 |
| Export formats | 3 | 3 | none |

`README.md` is 165 lines. The four undocumented commands are exactly the ones a user needs when a
build half-fails (`extract`/`resolve`/`induce` individually) or when they need to start over
(`reset`), i.e. the highest-stress moments.

---

## R-001: Documentation structure and depth

**Decision**: A flat `docs/` tree, maximum two levels deep, with four top-level entry pages
(`README.md` index, `install.md`, `quickstart.md`, `concepts.md`) and four intent directories
(`guides/`, `reference/`, `examples/`, `contributing/`) — 15 pages total. `docs/README.md` is the
index, so browsing to `docs/` on GitHub renders navigation automatically.

**Rationale**: The spec already mandates reader-intent grouping (FR-002) and two-link reachability
(SC-006). Intent groups map onto the Diátaxis quadrants without inventing a private taxonomy:
quickstart = tutorial, `guides/` + `examples/` = how-to, `reference/` = reference, `concepts.md` =
explanation. Capping depth at two guarantees SC-006 structurally rather than by review discipline.
Using `docs/README.md` (not `docs/index.md`) exploits GitHub's directory rendering, which is the
delivery surface for this feature since no site generator is in scope.

**Alternatives considered**:
- *Single `DOCUMENTATION.md`*: fails FR-001 and SC-006; a 2,000-line file has no navigation.
- *Numbered flat files* (`01-install.md`…): ordering encoded in filenames breaks on insertion and
  gives no grouping signal for the reference material, which is looked up rather than read in order.
- *Deeper nesting* (`docs/reference/cli/commands/build.md`): one page per command would push
  reachability past two links and create 16 near-empty files.
- *`mkdocs`/Sphinx site*: rejected per the spec's Assumptions — adds a dependency, a build step, and
  a publishing target for an alpha-stage tool with no hosting decided.

## R-002: MCP tool names — README is wrong, and docs must describe reality

**Finding**: The server registers tools under their Python function names. Verified by executing
`asyncio.run(mcp.list_tools())` against `kgmd.mcp_server`:

```text
['search', 'get_entity_tool', 'list_entities_tool', 'get_neighbors_tool',
 'find_path_tool', 'list_relations_tool', 'get_schema_tool']
```

`kgmd/mcp_server.py` calls `@mcp.tool()` with no `name=` argument at lines 43, 67, 78, 87, 96, 107,
123, so FastMCP derives each name from the function. `README.md`'s tool table advertises
`get_entity`, `list_entities`, `get_neighbors`, `find_path`, `list_relations`, `get_schema` — **6 of
7 names do not exist**. Only `search` is correct.

**Decision**: `docs/guides/mcp.md` documents the **real** registered names. This feature does not
rename anything. The coverage test derives expected names from the source so the pair can never
drift again.

**Rationale**: Documentation must describe the shipped system; a docs-scoped feature changing the
integration surface would be scope creep and a breaking change for any client config or saved prompt
referencing the current names. The `_tool` suffix exists only to avoid shadowing the imported
`kgmd.query` functions in the same module — an implementation artefact that leaked into the public
contract.

**Alternatives considered**:
- *Rename tools to the clean names in this feature*: rejected — breaking change to a public surface,
  needs its own spec, compatibility decision (alias both names?), and tests.
- *Document the clean names and "fix" reality later*: rejected outright — that is shipping knowingly
  false documentation.

**Follow-up (not part of this feature)**: run `/speckit.specify` for "rename MCP tools to drop the
`_tool` suffix with backward-compatible aliases". Until then the ugly names are the contract.

## R-003: Drift detection — introspection-based, bidirectional, zero new dependencies

**Decision**: One new module `tests/test_docs.py` that derives the real surface at test time and
asserts **bidirectional** agreement with the reference pages (nothing undocumented, nothing
documented that does not exist). Enumeration methods, all verified working:

| Surface | Enumeration method | Verified result |
|---|---|---|
| Commands | `kgmd.cli.main.commands.keys()` | 16 names |
| Parameters per command | `cmd.params` → `p.opts` | 49 total (9 arguments + 40 options) |
| Global options | `main.params` | `['--debug']` |
| Configuration keys | recursive flatten of `kgmd.config.DEFAULT_CONFIG` to dotted keys | 19 keys |
| MCP tools | `ast.parse("kgmd/mcp_server.py")`, collect `FunctionDef` names carrying an `@mcp.tool` decorator | 7 names |
| Export formats | `main.commands["export"].params[0].type.choices` | `jsonld`, `cypher`, `graphml` |
| Structured-output commands | presence of a param named `as_json` | 8 commands |

**Rationale**: Every surface is already introspectable, so coverage is a computable property rather
than a review checklist — which is what FR-041 demands. Deriving MCP names via `ast` rather than
`asyncio.run(mcp.list_tools())` keeps the test synchronous, avoids depending on FastMCP internals or
an event loop, and avoids importing a module whose import graph reaches `fastembed` (Constitution
Principle V forbids tests that could trigger a model download).

**Alternatives considered**:
- *`await mcp.list_tools()` in the test*: works (it is how R-002 was verified) but needs
  `asyncio.run` and imports the server module; the `ast` route is cheaper and hermetic.
- *A hand-maintained inventory file compared against docs*: just moves the drift problem to a third
  file nobody updates.
- *A separate `scripts/check_docs.py` + new CI step*: rejected — the constitution makes `pytest -v`
  the single blocking gate; a second enforcement path is a second convention for no gain.
- *`ruff`/markdown linters for prose*: no value against drift, and adds a dependency.

## R-004: Per-page version stamping

**Decision**: Every page carries, as its second line, exactly:

```text
> Applies to kgmd 0.1.x
```

The test extracts the stamp from every `docs/**/*.md` file and asserts the minor version matches
`kgmd.__version__` (`0.1.0` → `0.1.x`), failing if any page is missing or stale.

**Rationale**: Satisfies FR-004 with one greppable line and makes a version bump mechanically
detectable instead of silently invalidating 15 pages. A blockquote renders visibly on GitHub without
front-matter support, which plain markdown rendering lacks.

**Alternatives considered**:
- *YAML front matter*: GitHub renders it as a raw table in plain markdown files; ugly with no site
  generator.
- *Single version note on the index only*: a reader landing on a deep page from a search engine sees
  no version context.
- *Exact patch version per page*: forces edits to 15 pages on every patch release; the release
  process would route around it immediately.

## R-005: Sample corpus for reproducible examples

**Decision**: Reuse the existing `tests/fixtures/*.md` (7 files: `acme_corp.md`,
`brian_anderson.md`, `digital_transformation.md`, `partnerships.md`, `quarterly_review.md`,
`sarah_chen.md`, `tech_stack.md`) as the single canonical example corpus. Walkthroughs that show
exact output state "requires a git clone" and reference that path. The quickstart additionally
carries a self-contained heredoc that creates a two-note miniature corpus inline, for readers who
installed from PyPI and have no checkout; its expected output is described qualitatively (shape, not
counts). The test asserts every fixture filename referenced by a doc page exists on disk.

**Rationale**: Honours the spec's assumption of reusing shipped sample notes and avoids a second
corpus that would drift from the fixtures the test suite already pins. The heredoc closes the real
gap that fixtures are not in the wheel (`hatch` packages `kgmd/` only), so a `pip install` reader
can still complete the quickstart. Keeping exact counts out of the heredoc path prevents documented
numbers from depending on nondeterministic LLM output.

**Alternatives considered**:
- *Copy the fixtures into `docs/examples/notes/`*: two copies of the same notes, guaranteed to
  diverge; the test-asserted counts would silently stop matching the documented ones.
- *Ship the sample corpus inside the wheel*: changes packaging and adds weight to every install to
  serve a one-time onboarding need.
- *Add a `kgmd init --sample` flag*: a code change, out of scope for a documentation feature.

## R-006: Verifying examples without provider calls

**Decision**: Split verification by determinism.
- **Automated (in `pytest`, every run)**: surface coverage, bidirectional reference agreement,
  internal link integrity, version stamps, quoted-error-string existence, and agreement between
  documented command/option names and the real Click tree.
- **Manual (pre-release checklist in `docs/contributing/release.md`)**: actually run every
  provider-calling example against `tests/fixtures/` and confirm it completes as written (SC-004).

**Rationale**: Executing `kgmd build` in CI needs a real credential and makes nondeterministic paid
calls — a direct violation of Constitution Principle V and of FR-044/SC-011. Everything that *can*
be checked deterministically is, and the residue becomes an explicit, dated release step rather than
an unstated hope.

**Alternatives considered**:
- *Record/replay provider responses (VCR-style cassettes)*: would let CI run full builds, but adds a
  dependency, a large fixture corpus, and a second mocking convention alongside the existing
  `patch("kgmd.llm.litellm.completion")` boundary. Reconsider only if manual verification proves
  unreliable.
- *A `--dry-run` flag to exercise commands without provider calls*: a code change, out of scope.
- *Trusting review*: this is exactly what produced the 6 wrong tool names.

## R-007: Quoting error strings that contain interpolation

**Decision**: Troubleshooting entries quote the **literal prefix up to the first interpolated
value**, in an inline code span on a line beginning `**Symptom**:`. Example: the source raises
`f"Database not found: {db_path}"`, so the page quotes `Database not found:`. The test extracts every
such code span and asserts it appears verbatim in some `kgmd/**/*.py` source file.

**Rationale**: Makes FR-031 mechanically enforceable despite f-strings, and keeps the page findable
by pasting the head of an error message into a search box — which is how users actually search.
Requiring full messages would be unenforceable; requiring paraphrase would make the page unfindable.

**Alternatives considered**:
- *Assign error codes and document those*: better long-term, but requires changing every raise site
  — a code change, out of scope.
- *Regex-matching the whole f-string template*: brittle against any rewording, and the test would
  fail for cosmetic edits without catching real drift.

## R-008: Link integrity

**Decision**: The test resolves every markdown link target in `docs/**/*.md` and `README.md` that is
not an external URL (`http://`, `https://`, `mailto:`) against the filesystem, relative to the
containing file, and asserts it exists. Fragment-only links (`#anchor`) are validated against the
headings of the target file. External URLs are **not** fetched.

**Rationale**: Satisfies FR-042 while keeping the check offline and instantaneous. Link rot on
external sites is not detectable without network access, which Principle V forbids in the gate.

**Alternatives considered**:
- *`lychee`/`markdown-link-check` in CI*: new dependency, new CI step, and network flakiness that
  would make the blocking gate unreliable.
- *Checking anchors across files too*: deferred; heading-anchor slugification differs between
  renderers, so cross-file fragment checking would produce false failures.

## R-009: README's new role

**Decision**: `README.md` keeps project overview, feature bullets, install, a ~10-line "shortest
path" snippet, and a link table into `docs/`. Its configuration dump, MCP tool table, and export
list move into `docs/reference/`. The wrong MCP tool names are corrected as part of this change even
though the table is being replaced by a link — the file must not ship one more release with false
names.

**Rationale**: FR-003 makes the README orientation and `docs/` depth. PyPI renders the README as the
package description, so it must stand alone for a reader who never reaches the repository — hence
keeping install and a minimal usage snippet rather than reducing it to pure links.

**Alternatives considered**:
- *README as a pure pointer file*: degrades the PyPI landing page, which is the tool's storefront.
- *Leave the README untouched and let `docs/` duplicate it*: creates the exact "two sources
  disagree" edge case the spec calls out.

## R-010: Platform-specific paths (verified, not guessed)

**Decision**: `docs/reference/configuration.md` states the global configuration path per platform,
resolved from `platformdirs` 4.x with `appname="kgmd"`:

| Platform | Global config file |
|---|---|
| macOS | `~/Library/Application Support/kgmd/config.yaml` |
| Linux/BSD | `~/.config/kgmd/config.yaml` (honours `XDG_CONFIG_HOME`) |
| Windows | `%LOCALAPPDATA%\kgmd\kgmd\config.yaml` |

**Rationale**: The macOS and Linux values were resolved by executing `platformdirs.macos.MacOS` and
`platformdirs.unix.Unix` in the project venv. The Windows value cannot be resolved off-platform
(`NotImplementedError` from `get_win_folder_via_ctypes`), so it was derived by reading
`platformdirs/windows.py`: `user_config_dir` returns `user_data_dir` (line 57-59), which is
`%LOCALAPPDATA%` joined with `appauthor or appname` then `appname` (lines 29-48) — the doubled
`kgmd\kgmd` is correct because the project passes no `appauthor`.

**Note for implementation**: the doubled path is surprising enough that the page should show it
explicitly rather than saying "the platform equivalent", which is what the README says today. The
Windows row MUST be confirmed on a Windows machine before release; flag it in the release checklist.

**Alternatives considered**:
- *Say "platform-dependent, run `kgmd` to find out"*: there is no command that prints the resolved
  config path, so the reader has no way to find out.
- *Document only macOS/Linux*: the classifier list claims general Python 3.10+ support; silently
  dropping Windows readers is worse than a flagged-for-confirmation row.

## R-011: Documenting inert and divergent configuration

**Decision**: `docs/reference/configuration.md` marks the three constitution-recorded inert keys
(`extraction.max_entities_per_chunk`, `extraction.max_relations_per_chunk`,
`induction.include_attribute_summary`) as **"accepted but currently has no effect"**, and documents
`llm.max_tokens` with a note that the extraction stage applies its own lower internal default, so
raising the key may not raise the extraction limit.

**Rationale**: FR-017 requires disclosure. The constitution already records both as debt; the
documentation's job is to stop users tuning knobs that do nothing, not to hide the defect. Silence
here would cause exactly the support load this feature exists to remove.

**Alternatives considered**:
- *Omit the inert keys*: a user reading `.kgmd/config.yaml` (written on `init`) sees them and will
  ask; an undocumented key looks like a documentation gap rather than a known defect.
- *Fix the code first*: out of scope for this feature; the divergence is already tracked by the
  constitution's "touch it, fix it or re-justify it" rule.

## R-012: Where the checks run

**Decision**: `tests/test_docs.py`, executed by the existing `make test` / CI `pytest -v`. No new
CI job, no pre-commit hook, no new Make target.

**Rationale**: The constitution names `ruff check .` + `pytest -v` as the single blocking gate, and
the repository has no pre-commit configuration to extend. Documentation failures therefore block the
same way behavioural failures do — which is the point of FR-040.

**Alternatives considered**:
- *A dedicated `make docs-check` target*: an unenforced target is a suggestion, not a gate.
- *A separate CI workflow*: splits the signal and lets docs failures be ignored as "not the real
  build".
