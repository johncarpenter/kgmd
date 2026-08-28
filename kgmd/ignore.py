"""Gitignore-style exclusion rules read from a corpus-root `.kgmdignore` file.

Stdlib only, and imports nothing from kgmd: this is a leaf module.

Patterns are compiled to fully anchored regexes at parse time and matched against
corpus-relative POSIX paths. The supported subset is documented in
docs/reference/configuration.md; the two deliberate departures from git are that a
negation *can* re-include a file inside an excluded directory, and that character
classes and backslash escapes are not supported (they match literally, so an
unsupported pattern excludes nothing rather than excluding too much).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

IGNORE_FILENAME = ".kgmdignore"

DEFAULT_IGNORE_TEMPLATE = """\
# .kgmdignore — paths kgmd should not index.
#
# Every indexed file is chunked and sent to a language model, one call per chunk,
# so excluding material with no knowledge-graph value saves real money.
#
# Patterns match paths relative to this directory, always with '/' separators.
# Blank lines and lines starting with '#' are ignored. Rules are applied in order
# and the last matching rule wins.
#
# Nothing below is active — uncomment or add your own.
#
# Skip a whole directory and everything under it:
# archive/
# drafts/
#
# Skip files by glob. '*' does not cross '/', '**' spans any number of directories:
# **/CHANGELOG.md
# *-template.md
#
# Anchor a pattern to this directory with a leading '/':
# /README.md
#
# Re-include something an earlier rule excluded, with '!':
# !archive/2024-decisions.md
#
# Paths with a dot-prefixed component (.kgmd/, .git/) are always skipped and
# cannot be re-included with '!'.
"""


@dataclass(frozen=True)
class IgnoreRule:
    """One parsed line of `.kgmdignore`."""

    pattern: str
    regex: re.Pattern[str]
    negated: bool
    dir_only: bool
    line_number: int


def parse_ignore_rules(text: str) -> list[IgnoreRule]:
    """Parse `.kgmdignore` text into ordered rules.

    Comments, blank lines, and degenerate rules yield nothing. Order is the file's
    order and is significant: the last matching rule decides.
    """
    rules: list[IgnoreRule] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        negated = line.startswith("!")
        if negated:
            line = line[1:].strip()

        dir_only = line.endswith("/")
        line = line.rstrip("/")
        if not line:
            continue

        rules.append(
            IgnoreRule(
                pattern=line,
                regex=_compile(line),
                negated=negated,
                dir_only=dir_only,
                line_number=line_number,
            )
        )
    return rules


def load_ignore_rules(root: Path) -> list[IgnoreRule]:
    """Read `<root>/.kgmdignore`. Absent file yields no rules.

    A file that exists but cannot be read or decoded is an error: silently treating
    it as absent would index everything the user meant to exclude.
    """
    path = root / IGNORE_FILENAME
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(
            f"Could not read {IGNORE_FILENAME} at {path}: {exc}. "
            f"It must be UTF-8 text. Fix or remove the file, then re-run."
        ) from exc
    return parse_ignore_rules(text)


def is_ignored(rel_path: str, rules: list[IgnoreRule]) -> bool:
    """Whether a corpus-relative path is excluded by these rules.

    Each rule is tested against the path and against every ancestor directory of
    the path, so a directory rule covers its whole subtree. The last matching rule
    decides, which is what lets a negation re-include a file inside an excluded
    directory.
    """
    if not rules:
        return False

    ancestors = _ancestors(rel_path)
    ignored = False
    for rule in rules:
        targets = ancestors if rule.dir_only else (rel_path, *ancestors)
        if any(rule.regex.match(target) for target in targets):
            ignored = not rule.negated
    return ignored


def write_default_ignore_file(path: Path) -> bool:
    """Write the starter `.kgmdignore`, never clobbering an existing file.

    Returns True if the file was written.
    """
    if path.exists():
        return False
    path.write_text(DEFAULT_IGNORE_TEMPLATE, encoding="utf-8")
    return True


def _ancestors(rel_path: str) -> tuple[str, ...]:
    """Strict ancestor directories of a path, deepest first."""
    parts = rel_path.split("/")[:-1]
    return tuple("/".join(parts[: i + 1]) for i in reversed(range(len(parts))))


def _compile(pattern: str) -> re.Pattern[str]:
    """Compile a pattern to a fully anchored regex over a '/'-separated path."""
    anchored = "/" in pattern
    body = _translate(pattern.lstrip("/"))
    prefix = "" if anchored else "(?:.*/)?"
    return re.compile(rf"\A{prefix}{body}\Z")


def _translate(pattern: str) -> str:
    parts = pattern.split("/")
    out: list[str] = []
    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        if part == "**":
            # Zero or more whole segments. As the final segment, anything at all.
            out.append(".*" if is_last else "(?:[^/]+/)*")
            continue
        out.append(_translate_segment(part))
        if not is_last:
            out.append("/")
    return "".join(out)


def _translate_segment(segment: str) -> str:
    out: list[str] = []
    for char in segment:
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
    return "".join(out)
