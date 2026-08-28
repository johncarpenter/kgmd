"""Tests for CLI-level guarantees that cannot be observed from the library.

Most command behavior is tested through the function that backs it. Two promises
only exist at the CLI boundary: that `kgmd build --dry-run` creates no database,
and that `--json` is refused without `--dry-run`.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from kgmd.cli import main


def test_dry_run_creates_no_database(tmp_corpus):
    """FR-017: a dry run must not create graph.db for a never-built corpus."""
    kgmd_dir = tmp_corpus / ".kgmd"
    kgmd_dir.mkdir()
    db_path = kgmd_dir / "graph.db"
    assert not db_path.exists()

    result = CliRunner().invoke(main, ["build", str(tmp_corpus), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert not db_path.exists(), "a dry run created a database"
    assert "Resolved" in result.output


def test_dry_run_json_is_the_only_output(tmp_corpus):
    (tmp_corpus / ".kgmd").mkdir()
    (tmp_corpus / "archive").mkdir()
    (tmp_corpus / "archive" / "old.md").write_text("# old\n")
    (tmp_corpus / ".kgmdignore").write_text("archive/\n")

    result = CliRunner().invoke(main, ["build", str(tmp_corpus), "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["ignored"] == ["archive/old.md"]
    assert report["counts"]["would_remove"] == 0


def test_json_without_dry_run_is_refused(tmp_corpus):
    """--json implying --dry-run would make `kgmd build --json` silently not build."""
    (tmp_corpus / ".kgmd").mkdir()

    result = CliRunner().invoke(main, ["build", str(tmp_corpus), "--json"])

    assert result.exit_code != 0
    assert "--json requires --dry-run." in result.output


def test_init_writes_a_starter_ignore_file(tmp_path):
    corpus = tmp_path / "fresh"
    corpus.mkdir()

    result = CliRunner().invoke(main, ["init", "--path", str(corpus)])

    assert result.exit_code == 0, result.output
    ignore_path = corpus / ".kgmdignore"
    assert ignore_path.is_file()
    assert ignore_path.read_text().lstrip().startswith("#")


def test_init_never_clobbers_an_existing_ignore_file(tmp_path):
    corpus = tmp_path / "fresh"
    corpus.mkdir()
    (corpus / ".kgmdignore").write_text("archive/\n")

    CliRunner().invoke(main, ["init", "--path", str(corpus)])

    assert (corpus / ".kgmdignore").read_text() == "archive/\n"
