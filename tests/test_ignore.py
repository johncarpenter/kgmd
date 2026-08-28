"""Tests for .kgmdignore parsing and matching semantics.

Pure unit tests: no filesystem, no database, no model. The contract these assert is
docs/reference/configuration.md, and every case here is a promise to users who have
written a .kgmdignore.
"""

from __future__ import annotations

import pytest

from kgmd.ignore import (
    DEFAULT_IGNORE_TEMPLATE,
    is_ignored,
    parse_ignore_rules,
)


def ignored(text: str, path: str) -> bool:
    return is_ignored(path, parse_ignore_rules(text))


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------


def test_comments_and_blank_lines_yield_no_rules():
    text = "# a comment\n\n   \n\t\n# another\n"
    assert parse_ignore_rules(text) == []


def test_trailing_and_leading_whitespace_is_stripped():
    (rule,) = parse_ignore_rules("   archive/   \n")
    assert rule.pattern == "archive"
    assert rule.dir_only is True


def test_bang_sets_negation_and_slash_sets_dir_only():
    negated, plain = parse_ignore_rules("!archive/2024.md\nnotes/\n")
    assert (negated.negated, negated.dir_only) == (True, False)
    assert (plain.negated, plain.dir_only) == (False, True)


def test_degenerate_lines_yield_no_rules():
    assert parse_ignore_rules("!\n/\n!/\n//\n") == []


def test_line_numbers_are_one_based_and_track_the_source_file():
    rules = parse_ignore_rules("# comment\n\narchive/\n\ndrafts/\n")
    assert [r.line_number for r in rules] == [3, 5]


def test_rule_order_is_preserved():
    rules = parse_ignore_rules("b\na\nc\n")
    assert [r.pattern for r in rules] == ["b", "a", "c"]


def test_starter_template_parses_to_nothing():
    assert parse_ignore_rules(DEFAULT_IGNORE_TEMPLATE) == []


# --------------------------------------------------------------------------------------
# Matching: globs
# --------------------------------------------------------------------------------------


def test_no_rules_never_ignores():
    assert is_ignored("anything/at/all.md", []) is False


def test_star_does_not_cross_a_separator():
    # The reason fnmatch is unusable here: its '*' would match 'notes/deep'.
    assert ignored("/notes/*.md", "notes/a.md") is True
    assert ignored("/notes/*.md", "notes/deep/a.md") is False


def test_question_mark_matches_exactly_one_non_separator_character():
    assert ignored("/a?.md", "ab.md") is True
    assert ignored("/a?.md", "abc.md") is False
    assert ignored("/a?.md", "a/b.md") is False


@pytest.mark.parametrize(
    "path,expected",
    [
        ("CHANGELOG.md", True),
        ("docs/CHANGELOG.md", True),
        ("a/b/c/CHANGELOG.md", True),
        ("docs/CHANGELOG.txt", False),
    ],
)
def test_double_star_spans_any_number_of_segments_including_none(path, expected):
    assert ignored("**/CHANGELOG.md", path) is expected


def test_double_star_in_the_middle_spans_several_segments():
    text = "a/**/b.md"
    assert ignored(text, "a/b.md") is True
    assert ignored(text, "a/x/b.md") is True
    assert ignored(text, "a/x/y/z/b.md") is True
    assert ignored(text, "other/b.md") is False


def test_trailing_double_star_covers_the_subtree():
    assert ignored("archive/**", "archive/deep/old.md") is True
    assert ignored("archive/**", "notes/old.md") is False


# --------------------------------------------------------------------------------------
# Matching: anchoring
# --------------------------------------------------------------------------------------


def test_leading_slash_anchors_at_the_corpus_root():
    assert ignored("/README.md", "README.md") is True
    assert ignored("/README.md", "notes/README.md") is False


def test_interior_slash_anchors_at_the_corpus_root():
    assert ignored("notes/archive/", "notes/archive/a.md") is True
    assert ignored("notes/archive/", "other/notes/archive/a.md") is False


def test_pattern_without_a_slash_matches_at_any_depth():
    assert ignored("*-template.md", "msa-template.md") is True
    assert ignored("*-template.md", "notes/deep/msa-template.md") is True
    assert ignored("*-template.md", "notes/msa.md") is False


def test_bare_star_matches_everything():
    # The destructive case the empty-resolved-set guard exists for.
    assert ignored("*", "a.md") is True
    assert ignored("*", "notes/deep/a.md") is True


# --------------------------------------------------------------------------------------
# Matching: directories
# --------------------------------------------------------------------------------------


def test_directory_rule_covers_the_whole_subtree():
    assert ignored("archive/", "archive/old.md") is True
    assert ignored("archive/", "archive/deep/old.md") is True
    assert ignored("archive/", "notes/old.md") is False


def test_directory_rule_matches_a_directory_at_any_depth():
    assert ignored("archive/", "notes/archive/old.md") is True


def test_directory_only_rule_does_not_match_a_file_of_that_name():
    assert ignored("archive/", "archive") is False
    assert ignored("archive", "archive") is True


def test_rule_without_trailing_slash_still_covers_a_subtree():
    assert ignored("archive", "archive/old.md") is True


# --------------------------------------------------------------------------------------
# Matching: ordering and negation
# --------------------------------------------------------------------------------------


def test_last_matching_rule_wins():
    assert ignored("*.md\n!keep.md\n", "keep.md") is False
    assert ignored("!keep.md\n*.md\n", "keep.md") is True


def test_negation_re_includes_a_file_inside_an_excluded_directory():
    """The deliberate divergence from git, which refuses this."""
    text = "archive/\n!archive/2024-decisions.md\n"
    assert ignored(text, "archive/2024-decisions.md") is False
    assert ignored(text, "archive/old.md") is True


def test_negation_can_re_include_a_whole_directory():
    text = "archive/\n!archive/keep/\n"
    assert ignored(text, "archive/keep/a.md") is False
    assert ignored(text, "archive/other/a.md") is True


def test_negation_alone_ignores_nothing():
    assert ignored("!keep.md\n", "keep.md") is False
    assert ignored("!keep.md\n", "other.md") is False


# --------------------------------------------------------------------------------------
# Unsupported constructs fail toward inclusion
# --------------------------------------------------------------------------------------


def test_character_class_is_treated_literally_and_excludes_nothing():
    assert ignored("[a-z].md", "a.md") is False
    assert ignored("[a-z].md", "[a-z].md") is True


def test_regex_metacharacters_in_a_pattern_are_escaped():
    assert ignored("a+b.md", "aab.md") is False
    assert ignored("a+b.md", "a+b.md") is True
    assert ignored("notes.md", "notesXmd") is False
