# Feature Specification: Project Documentation Set

**Feature Branch**: `main` (no feature branch created — no `before_specify` git hook is registered)

**Created**: 2026-08-28

**Status**: Draft

**Input**: User description: "The application needs a documentation folder and extensive documentation on how to install, use and maintain the application. Some examples, quickstarts and use-cases"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Get from zero to a queryable graph (Priority: P1)

A developer who has just discovered the tool wants to try it on their own folder of markdown
notes. They need to know what they must have installed, how to install the tool, what credential
to set, and the exact sequence of commands that turns their notes into something they can query —
without reading source code and without guessing.

**Why this priority**: This is the adoption gate. If a first-time user cannot reach a working graph,
no other documentation matters. It is also where the tool has the most environment-specific failure
modes (interpreter capability, provider credentials), so it carries the highest support cost.

**Independent Test**: Hand the install guide plus quickstart to someone who has never used the tool,
on a clean machine, and observe them reach a successful graph build and at least one successful
query using only the documentation. Delivers standalone value even if no other documentation page
exists.

**Acceptance Scenarios**:

1. **Given** a clean machine with a supported interpreter, **When** the reader follows the install
   page top to bottom, **Then** the tool's version check succeeds and the reader is told how to
   confirm the install worked before continuing.
2. **Given** an installed tool and a folder of markdown files, **When** the reader follows the
   quickstart, **Then** they initialize a corpus, set a provider credential, build the graph, and
   run at least one query that returns results — with expected output shown for each step.
3. **Given** an interpreter that cannot load database extensions, **When** the build fails, **Then**
   the install page's prerequisites section names this exact symptom and gives the fix before the
   reader has to search elsewhere.
4. **Given** no provider credential is set, **When** the reader reaches the build step, **Then** the
   quickstart has already told them which credential is required and how to set it.

---

### User Story 2 - Look up any command, option, or setting (Priority: P2)

A regular user knows roughly what they want ("list only organizations", "raise the similarity
threshold", "get machine-readable output") and needs a complete reference to find the exact command,
flag, or configuration key — including the ones the current overview never mentions.

**Why this priority**: The tool exposes a substantially larger surface than the current overview
documents: several pipeline and lifecycle commands, plus every configuration key, are effectively
undiscoverable today. This is the highest-volume day-to-day need after onboarding.

**Independent Test**: Take a list of every user-visible command, option, configuration key, output
format, and integration tool, and confirm each one appears in the reference with its purpose,
default, and an example. Delivers value independently as a lookup artifact.

**Acceptance Scenarios**:

1. **Given** the command reference, **When** a reader scans it, **Then** every command the tool
   accepts is listed — including the individual pipeline stages and the destructive reset
   operation — each with its purpose, arguments, options, and defaults.
2. **Given** a reader who wants machine-readable output, **When** they consult any query command's
   entry, **Then** the reference states whether structured output is available and shows both the
   human and structured form.
3. **Given** the configuration reference, **When** a reader looks up any setting, **Then** they see
   its default value, accepted values, effect, and which file it belongs in.
4. **Given** two configuration files with overlapping settings, **When** the reader consults the
   configuration reference, **Then** the precedence between the per-corpus file and the
   machine-wide file is stated explicitly with a worked example.
5. **Given** the integration reference, **When** a reader sets up an assistant client, **Then** all
   exposed integration tools are documented with inputs, outputs, and a copy-pasteable client
   configuration.

---

### User Story 3 - Operate and maintain a corpus over time (Priority: P3)

A user who has been running the tool for weeks adds and edits notes, wants to know what re-running
will cost, needs to recover from a bad state, and wants to understand what is safe to delete.

**Why this priority**: This is where silent data damage and surprise provider spend occur. The
behaviour is already well defined in the product but is almost entirely undocumented, so users
either avoid re-running or reset more than they need to.

**Independent Test**: Give an existing corpus and a maintenance guide to a user, then ask them to
add one file, re-run, and explain what work was repeated and what was skipped; then ask them to
recover from a changed embedding model. Both must be answerable from the guide alone.

**Acceptance Scenarios**:

1. **Given** an existing corpus, **When** the reader consults the maintenance guide, **Then** it
   explains which work is skipped on re-run, what triggers re-processing of a file, and how to force
   full reprocessing.
2. **Given** a user worried about provider cost, **When** they read the maintenance guide, **Then**
   it explains which stages call an external provider, how corpus size drives that volume, and how
   to preview or limit the work before committing to it.
3. **Given** a corpus in a bad state, **When** the reader consults recovery guidance, **Then** it
   distinguishes the reversible reset from the destructive one, states exactly what each removes,
   and names the single file that holds all state.
4. **Given** a user who wants to change the embedding model of an existing corpus, **When** they
   consult the guide, **Then** it states that this is not supported in place and gives the exact
   recovery path.
5. **Given** two simultaneous build attempts on one corpus, **When** the second is refused, **Then**
   the troubleshooting entry explains the locking behaviour and how to clear a stale lock.
6. **Given** a failed or partial run, **When** the reader needs evidence, **Then** the guide names
   the log location and states what is and is not recorded there.

---

### User Story 4 - Decide whether the tool fits a real job (Priority: P4)

A prospective adopter is evaluating the tool for a concrete purpose — personal knowledge notes,
meeting minutes feeding an assistant, or loading a graph into an external graph tool — and wants to
see a complete worked example with realistic input and expected output before investing time.

**Why this priority**: Worked use cases convert evaluation into adoption and reduce
"can it do X?" questions, but they depend on the reference material in P1–P3 already existing.

**Independent Test**: A reader picks one use-case walkthrough, runs it end to end against the
bundled sample notes, and reaches the shown output without consulting any other page except the
install guide.

**Acceptance Scenarios**:

1. **Given** the use-case section, **When** a reader browses it, **Then** at least three distinct
   end-to-end walkthroughs are available, each stating the goal, the input shape, the commands, the
   expected output, and the limits of the approach.
2. **Given** a walkthrough, **When** the reader has no data of their own, **Then** the walkthrough
   runs against sample notes shipped with the project so it is reproducible by anyone.
3. **Given** a walkthrough that produces an export, **When** the reader follows it, **Then** it
   shows what to do with the exported file in the named external tool.

---

### User Story 5 - Contribute or maintain the codebase (Priority: P5)

A contributor (or the author six months later) needs to understand how the pipeline fits together,
what the project's non-negotiable rules are, how to run checks, and how a release is cut.

**Why this priority**: "Maintain the application" includes maintaining the code, not just a corpus.
It is lowest priority because the audience is smallest and the governing rules already exist in the
project constitution; this work makes them discoverable rather than inventing them.

**Independent Test**: A new contributor uses the contributor guide alone to set up a development
environment, run the full local check sequence, and correctly describe where a new pipeline stage's
code, prompts, tests, and documentation must go.

**Acceptance Scenarios**:

1. **Given** the contributor guide, **When** a newcomer reads it, **Then** they can set up a
   development environment and run the same checks that gate the project's automated pipeline.
2. **Given** the architecture overview, **When** a contributor reads it, **Then** they can name each
   pipeline stage, the single place all persistent state lives, and the rule that keeps the command
   surface and the integration surface behaviourally identical.
3. **Given** a contributor about to add a user-visible capability, **When** they consult the guide,
   **Then** it states that documentation updates ship in the same change as the capability.
4. **Given** a maintainer cutting a release, **When** they follow the release section, **Then** the
   version-bump location, the publication trigger, and the prohibited manual shortcuts are stated.

---

### Edge Cases

- **Documentation drift**: a command gains an option, a configuration key is renamed, or a stage
  changes behaviour, and the documentation still describes the old behaviour. What makes drift
  visible before a reader hits it?
- **Version skew**: a reader on an older installed version follows documentation describing a newer
  capability. How does the reader know which version a page applies to?
- **Undocumented-by-omission**: a capability exists in the tool but appears in no page (the current
  state for several commands). What check catches a surface that has no documentation entry?
- **Broken navigation**: an internal cross-reference points at a moved or renamed page.
- **Cost surprise**: a reader copy-pastes an example that processes a large corpus and incurs
  unexpected provider spend. Which examples must carry a cost warning?
- **Credential leakage**: an example shows a real-looking key, or a reader pastes their key into a
  file that gets committed. How do examples model credential handling?
- **Platform divergence**: machine-wide configuration and assistant-client configuration live at
  different paths per operating system; a single hard-coded path misleads most readers.
- **Empty or hostile input**: a reader points the tool at a folder with no markdown, one enormous
  file, or files with no extractable entities, and needs to know whether that is a failure or a
  correct empty result.
- **Overlap with the existing overview**: the same instruction exists in two places and they
  disagree. Which one is authoritative?
- **Reader cannot satisfy prerequisites**: the reader's interpreter lacks the required database
  extension capability and they cannot rebuild it. Is there a documented alternative or a clear
  "not supported" statement?

## Requirements *(mandatory)*

### Functional Requirements

**Structure and navigation**

- **FR-001**: The project MUST contain a dedicated top-level documentation folder that holds all
  long-form documentation as plain-text files stored and versioned alongside the application.
- **FR-002**: The documentation set MUST provide a single entry index that lists every page grouped
  by reader intent (get started, use, integrate, operate, examples, contribute) so any topic is
  reachable within two links from the index.
- **FR-003**: The existing project overview MUST remain the shortest path to installation and MUST
  link into the documentation set rather than duplicating it; where the two overlap, the
  documentation set MUST be declared authoritative for depth and the overview for orientation.
- **FR-004**: Every page MUST state the tool version or version range it applies to.

**Installation**

- **FR-005**: An installation page MUST document all supported install methods, the supported
  interpreter versions, and how to verify a successful install before proceeding.
- **FR-006**: The installation page MUST document the interpreter capability required for the
  database extension, including the exact symptom of a non-capable interpreter and a working
  remedy for at least the common version-manager case.
- **FR-007**: The installation page MUST document which external provider credential is required,
  how to supply it via the environment, and MUST state that the tool never stores, prompts for, or
  logs credentials.
- **FR-008**: The installation page MUST state which capabilities work with no external credential
  at all (local embedding by default) versus which require one.

**Quickstart**

- **FR-009**: A quickstart page MUST take a reader from an installed tool to a queryable graph in a
  single ordered command sequence, with expected output shown for every step.
- **FR-010**: The quickstart MUST be completable against sample notes shipped with the project, so a
  reader without their own corpus can still finish it.
- **FR-011**: The quickstart MUST state, before the first provider-calling command, that the step
  incurs external provider usage, and give an indicative sense of volume for a small corpus.

**Reference**

- **FR-012**: A command reference MUST document every command the tool exposes — including corpus
  initialization, the combined build, each individual pipeline stage, every query command, statistics,
  schema display, export, the destructive reset, and the integration server — with purpose,
  arguments, options, defaults, and at least one example per command. No command may be omitted.
- **FR-013**: The command reference MUST document global options that apply across commands,
  including the diagnostic option that changes error verbosity.
- **FR-014**: For every command offering structured output, the reference MUST show both the human
  and the structured form, and state that structured output is the supported form for scripting.
- **FR-015**: A configuration reference MUST document every configuration key with its default,
  accepted values or range, effect on behaviour, and the stage it affects.
- **FR-016**: The configuration reference MUST document the precedence between the per-corpus
  configuration file and the machine-wide configuration file, including how the machine-wide
  location differs by operating system, with a worked merge example.
- **FR-017**: The configuration reference MUST identify any key that is currently accepted but has
  no effect, rather than implying it works.
- **FR-018**: An integration page MUST document every tool exposed to assistant clients with its
  inputs, outputs, and behaviour, plus a copy-pasteable client configuration and the platform-specific
  location of that client's configuration file.
- **FR-019**: An export page MUST document every supported export format, what each contains, and
  which external tool consumes it.

**Concepts**

- **FR-020**: A concepts page MUST explain the pipeline stages in order, what each stage reads and
  writes, and why the stages are separable.
- **FR-021**: The concepts page MUST explain the vocabulary a reader meets in output — document,
  chunk, entity, mention, relation, induced schema — in plain language.
- **FR-022**: The concepts page MUST state that all corpus state lives in one database file within
  the corpus's tool directory, and that deleting that file is a complete reset.

**Operations and maintenance**

- **FR-023**: A maintenance page MUST explain incremental behaviour: what is skipped on re-run, what
  change causes a file to be reprocessed, what downstream work is invalidated by a change, and how
  to force full reprocessing.
- **FR-024**: The maintenance page MUST document the reversible reset and the destructive reset
  separately, stating exactly what each removes and what each preserves.
- **FR-025**: The maintenance page MUST document the concurrency guarantee for builds, the observable
  behaviour when a second build is attempted, and how to clear a stale lock.
- **FR-026**: The maintenance page MUST document that the embedding model is fixed for the life of a
  corpus, the error a reader will see if they change it, and the supported recovery path.
- **FR-027**: The maintenance page MUST document the run log's location and state that it records
  call metadata only, never note content, prompts, responses, or credentials.
- **FR-028**: The maintenance page MUST give practical guidance on controlling external provider
  spend, including which stages call the provider and which settings change the volume of calls.
- **FR-029**: The maintenance page MUST document how to back up and relocate a corpus.

**Troubleshooting**

- **FR-030**: A troubleshooting page MUST use a symptom → cause → fix structure and MUST cover at
  minimum: missing provider credential, interpreter without database-extension support, command run
  outside an initialized corpus, embedding-model mismatch, a build blocked by another build, a
  provider response that cannot be parsed, and a build that produces zero entities.
- **FR-031**: Each troubleshooting entry MUST quote the user-visible error text a reader would
  actually see, so the page is findable by searching that text.

**Examples and use cases**

- **FR-032**: The documentation set MUST include at least three end-to-end use-case walkthroughs
  covering distinct goals, at minimum: building a searchable graph over personal notes; exposing a
  corpus to an assistant client and asking questions through it; and exporting a graph into an
  external graph or visualization tool.
- **FR-033**: Every walkthrough MUST state its goal, prerequisites, input shape, the exact command
  sequence, the expected output, and the limitations of the approach.
- **FR-034**: All examples MUST be copy-pasteable and MUST run against sample notes shipped with the
  project or clearly-described reader-supplied input; no example may depend on data the reader
  cannot obtain.
- **FR-035**: No example may contain a real or realistic-looking credential; credentials MUST always
  appear as an environment variable reference with an obvious placeholder value.

**Contributor and maintainer documentation**

- **FR-036**: A contributor page MUST document development environment setup and the exact local
  check sequence that mirrors the project's automated gate.
- **FR-037**: An architecture page MUST describe the module layering, the one-way dependency
  direction, the single shared query layer behind both user-facing surfaces, and where prompts,
  schema definitions, and tests live.
- **FR-038**: The contributor page MUST link to the project constitution as the governing document
  and MUST NOT restate its rules in a way that can drift from it.
- **FR-039**: A release page MUST document the version-bump location, the publication trigger, and
  the prohibited manual shortcuts.

**Accuracy and upkeep**

- **FR-040**: Any change to a user-visible surface — a command, an option, a configuration key, an
  export format, an integration tool, or an install prerequisite — MUST update the corresponding
  documentation page in the same change.
- **FR-041**: The documentation set MUST be checkable for completeness against the tool's actual
  surface, such that a command, option, configuration key, integration tool, or export format with
  no documentation entry is detectable rather than silently missing.
- **FR-042**: Internal cross-references within the documentation set MUST be verifiable, such that a
  reference to a missing or renamed page is detectable.
- **FR-043**: Documented command examples MUST be reproducible as written; every example MUST be
  re-verified against the shipped sample notes before a release.
- **FR-044**: Automated verification of documentation MUST NOT require external provider credentials
  or make live provider calls, in keeping with the project's hermetic-check rule.

### Key Entities *(include if feature involves data)*

- **Documentation Set**: The complete body of pages in the documentation folder; versioned with the
  application; has exactly one entry index and one authoritative page per topic.
- **Page**: A single topic document with a stated audience, an applicable version, and links to
  related pages. Belongs to exactly one reader-intent group.
- **Reference Entry**: A documented unit of user-visible surface — one command, one option, one
  configuration key, one integration tool, or one export format — carrying purpose, default,
  accepted values, and at least one example. Maps one-to-one onto a real surface in the tool.
- **Walkthrough**: A goal-oriented end-to-end example with prerequisites, input, ordered commands,
  expected output, and stated limitations. References a Sample Corpus.
- **Sample Corpus**: The set of example notes shipped with the project that walkthroughs and the
  quickstart run against, so every example is reproducible without reader-supplied data.
- **Troubleshooting Entry**: A symptom (quoted user-visible error text), its cause, and its fix.
- **Concept Term**: A vocabulary item a reader meets in output (document, chunk, entity, mention,
  relation, induced schema) with a plain-language definition, defined once and linked elsewhere.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reader with no prior exposure to the tool goes from nothing installed to a queryable
  graph in under 15 minutes of active work, using only the install page and the quickstart, on a
  clean machine.
- **SC-002**: 100% of user-visible surface has a documentation entry: every command the tool accepts
  (currently 16, including the four pipeline and lifecycle commands absent from today's overview),
  every command option, every configuration key, all 7 integration tools, and all 3 export formats.
- **SC-003**: Zero steps in the getting-started path require the reader to read application source
  code, inspect the database directly, or consult an external search engine.
- **SC-004**: 100% of documented command examples execute successfully as written against the
  shipped sample notes, verified before each release.
- **SC-005**: The troubleshooting page resolves the project's known top failure modes without
  escalation — at minimum the seven named in the requirements — each findable by searching the exact
  error text the reader sees.
- **SC-006**: Every documented topic is reachable within two links from the entry index.
- **SC-007**: At least three complete use-case walkthroughs exist, each reproducible end to end
  against the shipped sample notes by a reader with no data of their own.
- **SC-008**: Zero known mismatches between documented behaviour and actual behaviour at the moment
  of any release.
- **SC-009**: A first-time contributor sets up a working development environment and gets a clean
  local check run in under 10 minutes using only the contributor page.
- **SC-010**: A user can answer "what will re-running cost me and what will it redo?" and "how do I
  get back to a clean state?" directly from the maintenance page, without trial and error.
- **SC-011**: Documentation checks add no external provider calls and no credential requirement to
  the project's automated gate.

## Assumptions

- **Audience**: technically competent developers and practitioners comfortable with a terminal and a
  text editor. Not end-consumers; no GUI-oriented instruction is needed.
- **Authority split**: the existing project overview stays as the short orientation and install
  pointer; the documentation folder holds all depth. This preserves the project constitution's
  existing "documentation as contract" rule, which currently names the overview as the user-facing
  specification — that rule is read as extending to the documentation set, and the constitution
  SHOULD be amended to name both surfaces once this feature lands. No amendment is made by this
  specification.
- **Format and delivery**: plain-text markdown files committed in the repository, versioned with the
  package. Building or hosting a rendered documentation site, adding hosted search, and adding
  generated API reference are explicitly out of scope for this feature.
- **Reproducibility of examples**: the sample notes already shipped with the project are reused as
  the example corpus rather than inventing a new one, so examples stay reproducible and stay in step
  with existing tests.
- **Provider-calling examples**: examples that call an external provider are verified manually by a
  maintainer before release, not in the automated gate, because live provider calls are
  non-deterministic, cost money, and would violate the project's hermetic-check rule. Automated
  checks are limited to deterministic properties: surface coverage, cross-reference integrity, and
  agreement between documented command surfaces and the tool's own help output.
- **Versioning**: one documentation set tracking the current version of the package. No
  multi-version documentation, no separate documentation branch, no changelog-per-page.
- **Language**: English only.
- **"Maintain" covers both readings**: maintaining a corpus over time (operator) and maintaining the
  codebase (contributor). Both are in scope, as separate reader-intent groups.
- **Cost figures**: indicative volume guidance (order of magnitude for a small corpus) rather than
  quoted prices, since provider pricing changes independently of this project.
- **Out of scope**: video or interactive tutorials, translations, a public documentation site,
  per-page comment or feedback collection, and migration guides for versions that do not yet exist.
- **Dependency**: accurate documentation of commands, configuration keys, integration tools, and
  error text depends on those surfaces being stable at the time of writing; any surface changed
  during this work must be re-checked before release.
