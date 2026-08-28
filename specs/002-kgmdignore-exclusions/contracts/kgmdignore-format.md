# Contract: `.kgmdignore` file format

**Feature**: [../spec.md](../spec.md) | **Status**: authoritative for implementation and docs

This is a user-authored file format, so it is a public contract: once shipped, a corpus's
`.kgmdignore` must keep meaning what it meant. Everything below is normative.

## Location and discovery

- Exactly one file is read: `<corpus root>/.kgmdignore`.
- Absent file → empty ruleset → discovery behaves exactly as it did before this feature.
- Present but unreadable or not valid UTF-8 → hard error naming the file. Never silently ignored.
- Files named `.kgmdignore` in subdirectories are **not** read.
- The file is read fresh on every run. No caching, no invalidation step.

## Line grammar

```text
line        := blank | comment | rule
blank       := WS*
comment     := WS* "#" ANY*
rule        := "!"? pattern "/"?
pattern     := segment ( "/" segment )*
segment     := ( literal | "*" | "?" | "**" )+
```

Processing order per line:

1. Strip trailing whitespace.
2. If the result is empty, or its first non-whitespace character is `#`, produce no rule.
3. A leading `!` sets `negated` and is removed.
4. A trailing `/` sets `dir_only` and is removed.
5. If nothing remains, produce no rule.

## Matching

Patterns match the **corpus-relative path** with `/` separators on every platform. Matching is
**case-sensitive** regardless of the host filesystem.

| Construct | Matches |
|---|---|
| `*` | any run of characters, never crossing `/` |
| `?` | exactly one character, never `/` |
| `**` | any number of path segments; `a/**/b` also matches `a/b` |
| leading `/` | anchors the pattern at the corpus root |
| any interior `/` | anchors the pattern at the corpus root |
| no `/` anywhere | matches at any depth |
| trailing `/` | directory-only: the named directory and everything beneath it |

A pattern without a trailing `/` matches a file with that path **and** any path beneath a directory
with that path. So `archive` and `archive/` differ only in whether a *file* named `archive` matches.

**Not supported** (a pattern using these matches literally, so it excludes nothing rather than too
much):

- character classes — `[a-z]`, `[!abc]`
- backslash escapes for a literal `#`, `!`, or trailing space

## Precedence

Fixed, and not configurable:

```text
corpus.include  scopes the candidate set   (unchanged behavior)
        v
.kgmdignore     rules evaluated in file order, LAST MATCH WINS
        v
dot-path rule   applied last, NEVER overridable
```

For each candidate file, every rule is tested against the file's relative path and against each of
its ancestor directory prefixes. The last rule that matches decides: a negation re-admits, a normal
rule excludes.

A path with any dot-prefixed component (`.kgmd/`, `.git/`, `.claude/`) is excluded after all rule
evaluation. No pattern, negated or not, can re-admit it.

## Divergence from git — negation inside an excluded directory

git states: "It is not possible to re-include a file if a parent directory of that file is
excluded." **`.kgmdignore` does not have that limitation.** This works:

```text
archive/
!archive/2024-decisions.md
```

Result: `archive/2024-decisions.md` is indexed; everything else under `archive/` is not.

This is the motivating example from the source issue, and it is why rules are evaluated per file
against all ancestor prefixes rather than by pruning the directory walk.

## Worked example

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

Against a corpus containing:

| Path | Result | Deciding rule |
|---|---|---|
| `notes/today.md` | indexed | no rule matches |
| `archive/old.md` | excluded | `archive/` |
| `archive/2024-decisions.md` | indexed | `!archive/2024-decisions.md` (last match) |
| `drafts/idea.md` | excluded | `drafts/` |
| `docs/CHANGELOG.md` | excluded | `**/CHANGELOG.md` |
| `CHANGELOG.md` | excluded | `**/CHANGELOG.md` (`a/**/b` also matches `a/b`) |
| `notes/msa-template.md` | excluded | `*-template.md` (unanchored, any depth) |
| `.kgmd/notes.md` | excluded | dot-path rule, after all rules |

## Guarantees a change to this contract must preserve

1. An absent `.kgmdignore` never changes behavior.
2. The dot-path rule is never overridable.
3. Ordering semantics are last-match-wins, in file order.
4. An unsupported construct fails toward including files, never toward excluding them.
