# Specification Quality Checklist: Corpus Exclusions via `.kgmdignore`

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-28
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Validation Notes

Iteration 1 findings and resolutions:

1. **Implementation leak in Dependencies** — the original text named storage mechanics ("cascade
   behavior", "evidence links are nulled", "vector rows are not cascaded"). Rewritten in behavioral
   terms: discarding a note's text discards its entity mentions but leaves its search vectors and
   unsupported relations behind. The load-bearing risk is preserved without naming schema mechanics.

2. **Zero clarification markers** — the source issue leaves five points open. Each was resolved to
   the simplest correct option and recorded in Assumptions rather than deferred to the user:
   - *Negation* — in scope. The motivating example in the issue uses it and last-match-wins ordering
     needs no new dependency.
   - *Precedence* — allowlist scopes, ignore subtracts, negation re-admits, dot-path exclusion last
     and non-overridable (FR-007, FR-008).
   - *Inline config key* — rejected (FR-020). Two mechanisms for one job, and it would add a
     configuration key requiring its own documentation entry.
   - *Reusing `.gitignore`* — out of scope; conflates two concerns.
   - *Pruning split* — not split. Comparing the resolved file set against recorded document paths
     covers newly-ignored, deleted, and renamed files with one mechanism; an ignore-specific variant
     would be more work for less coverage. The issue's "document the limitation instead" escape is
     therefore not used.
   - *Preview / dry-run* — in scope as P3. Ignore rules are otherwise unverifiable before the spend
     they exist to prevent. Surfaced on the existing build path since there is no standalone ingest
     command.

3. **Terms retained deliberately** — `.kgmdignore`, pattern syntax, and the preview are user-facing
   surfaces named in the issue's acceptance criteria, not implementation choices. Domain nouns
   (document, chunk, entity mention, relation, search vector) appear only in Key Entities and
   Dependencies, where the template calls for the data the feature touches.

4. **Safety requirement added beyond the issue** — FR-015: an ignore ruleset that resolves to an
   empty file set must not silently empty an existing graph. Unified pruning makes a stray `*`
   pattern destructive, so this guard is required by the pruning decision above.

## Notes

- All items pass. Spec is ready for `/speckit.plan`.
- Items marked incomplete would require spec updates before `/speckit.clarify` or `/speckit.plan`.
