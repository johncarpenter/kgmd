"""Tests for corpus file discovery, .kgmdignore exclusion, and orphan pruning."""

from __future__ import annotations

import struct
from datetime import datetime, timezone

import pytest

from kgmd.ingest import (
    dry_run_report,
    ingest_documents,
    prune_missing_documents,
    scan_corpus_files,
)


def _rel(corpus, paths):
    return sorted(p.relative_to(corpus).as_posix() for p in paths)


# --------------------------------------------------------------------------------------
# Discovery: the resolved file set (Foundational)
# --------------------------------------------------------------------------------------


def test_scan_matches_plain_rglob_when_no_ignore_file(tmp_corpus):
    """With no .kgmdignore, the resolved set is every .md file minus dot-paths."""
    expected = sorted(
        p.relative_to(tmp_corpus).as_posix()
        for p in tmp_corpus.rglob("*.md")
        if not any(part.startswith(".") for part in p.relative_to(tmp_corpus).parts)
    )

    scan = scan_corpus_files(tmp_corpus, {})

    assert _rel(tmp_corpus, scan.included) == expected
    assert scan.ignored == []
    assert expected, "fixture corpus should contain markdown files"


def test_scan_groups_are_disjoint(initialized_corpus):
    """A path appears in exactly one group, and .kgmd/ lands in dotpath."""
    (initialized_corpus / ".kgmd" / "notes.md").write_text("# hidden\n")
    (initialized_corpus / "archive").mkdir()
    (initialized_corpus / "archive" / "old.md").write_text("# old\n")
    (initialized_corpus / ".kgmdignore").write_text("archive/\n")

    scan = scan_corpus_files(initialized_corpus, {})

    groups = [set(scan.included), set(scan.ignored), set(scan.dotpath)]
    for i, left in enumerate(groups):
        for right in groups[i + 1 :]:
            assert not left & right

    assert _rel(initialized_corpus, scan.ignored) == ["archive/old.md"]
    assert ".kgmd/notes.md" in _rel(initialized_corpus, scan.dotpath)


def test_scan_honours_corpus_include(tmp_corpus):
    """corpus.include still scopes the candidate set to literal paths."""
    (tmp_corpus / "notes").mkdir()
    (tmp_corpus / "notes" / "a.md").write_text("# a\n")

    scan = scan_corpus_files(tmp_corpus, {"corpus": {"include": ["notes"]}})

    assert _rel(tmp_corpus, scan.included) == ["notes/a.md"]


# --------------------------------------------------------------------------------------
# Discovery: .kgmdignore interaction (US1)
# --------------------------------------------------------------------------------------


def _corpus_with_worked_example(root):
    for name in ("notes", "archive", "drafts", "docs"):
        (root / name).mkdir()
    (root / "notes" / "today.md").write_text("# today\n")
    (root / "notes" / "msa-template.md").write_text("# template\n")
    (root / "archive" / "old.md").write_text("# old\n")
    (root / "archive" / "2024-decisions.md").write_text("# decisions\n")
    (root / "drafts" / "idea.md").write_text("# idea\n")
    (root / "docs" / "CHANGELOG.md").write_text("# changelog\n")
    (root / "CHANGELOG.md").write_text("# root changelog\n")
    (root / ".kgmdignore").write_text(
        "# skip archived notes\n"
        "archive/\n"
        "drafts/\n"
        "\n"
        "# skip generated or boilerplate files\n"
        "**/CHANGELOG.md\n"
        "*-template.md\n"
        "\n"
        "# but keep this one\n"
        "!archive/2024-decisions.md\n"
    )


def test_worked_example_resolves_as_documented(tmp_path):
    """The example from contracts/kgmdignore-format.md, asserted path by path."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _corpus_with_worked_example(corpus)

    scan = scan_corpus_files(corpus, {})

    assert _rel(corpus, scan.included) == [
        "archive/2024-decisions.md",
        "notes/today.md",
    ]
    assert _rel(corpus, scan.ignored) == [
        "CHANGELOG.md",
        "archive/old.md",
        "docs/CHANGELOG.md",
        "drafts/idea.md",
        "notes/msa-template.md",
    ]


def test_ignore_subtracts_from_corpus_include(tmp_path):
    """Both mechanisms present: include scopes, ignore subtracts from it."""
    corpus = tmp_path / "corpus"
    (corpus / "notes" / "archive").mkdir(parents=True)
    (corpus / "notes" / "keep.md").write_text("# keep\n")
    (corpus / "notes" / "archive" / "drop.md").write_text("# drop\n")
    (corpus / "outside.md").write_text("# outside\n")
    (corpus / ".kgmdignore").write_text("notes/archive/\n")

    scan = scan_corpus_files(corpus, {"corpus": {"include": ["notes"]}})

    assert _rel(corpus, scan.included) == ["notes/keep.md"]
    assert _rel(corpus, scan.ignored) == ["notes/archive/drop.md"]
    # outside.md was never a candidate; it is not reported as ignored.
    assert "outside.md" not in _rel(corpus, scan.ignored)


def test_negation_cannot_readmit_a_dotpath(initialized_corpus):
    """The dot-path rule is applied last and is not overridable (FR-008)."""
    (initialized_corpus / ".kgmd" / "notes.md").write_text("# hidden\n")
    (initialized_corpus / ".kgmdignore").write_text("!.kgmd/notes.md\n")

    scan = scan_corpus_files(initialized_corpus, {})

    assert ".kgmd/notes.md" not in _rel(initialized_corpus, scan.included)
    assert ".kgmd/notes.md" in _rel(initialized_corpus, scan.dotpath)


def test_comments_only_ignore_file_excludes_nothing(tmp_corpus):
    """An empty or all-comment file behaves exactly like no file at all."""
    baseline = scan_corpus_files(tmp_corpus, {})
    (tmp_corpus / ".kgmdignore").write_text("# just a comment\n\n   \n")

    scan = scan_corpus_files(tmp_corpus, {})

    assert scan.included == baseline.included
    assert scan.ignored == []


def test_starter_template_excludes_nothing(tmp_corpus):
    """kgmd init's starter file must not change what a fresh corpus indexes (FR-019)."""
    from kgmd.ignore import DEFAULT_IGNORE_TEMPLATE, parse_ignore_rules

    assert parse_ignore_rules(DEFAULT_IGNORE_TEMPLATE) == []

    baseline = scan_corpus_files(tmp_corpus, {})
    (tmp_corpus / ".kgmdignore").write_text(DEFAULT_IGNORE_TEMPLATE)

    assert scan_corpus_files(tmp_corpus, {}).included == baseline.included


def test_undecodable_ignore_file_fails_loudly(tmp_corpus):
    """A present-but-unreadable file must not be silently treated as absent (FR-006)."""
    (tmp_corpus / ".kgmdignore").write_bytes(b"archive/\n\xff\xfe invalid \x80\n")

    with pytest.raises(RuntimeError, match=r"\.kgmdignore"):
        scan_corpus_files(tmp_corpus, {})


# --------------------------------------------------------------------------------------
# Pruning helpers (US2)
# --------------------------------------------------------------------------------------


def _seed_document(conn, path, *, chunk_count=1):
    """Insert a document with chunks, one mention per chunk, and hand-packed vectors."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO documents (path, content_hash, size_bytes, mtime, ingested_at,"
        " last_extracted_hash) VALUES (?, ?, ?, ?, ?, ?)",
        (path, f"hash-{path}", 10, 0.0, now, f"hash-{path}"),
    )
    doc_id = cur.lastrowid
    chunk_ids = []
    for index in range(chunk_count):
        cur = conn.execute(
            "INSERT INTO chunks (document_id, chunk_index, content, char_start, char_end,"
            " token_count) VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, index, f"text of {path} #{index}", 0, 10, 3),
        )
        chunk_ids.append(cur.lastrowid)
    return doc_id, chunk_ids


def _vector(dim=384, fill=0.1):
    return struct.pack(f"{dim}f", *([fill] * dim))


def _seed_extraction_run(conn):
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO extraction_runs (started_at, model, status) VALUES (?, ?, ?)",
        (now, "test-model", "completed"),
    )
    return cur.lastrowid


def _seed_entity(conn, name, entity_type="Person"):
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO entities (canonical_name, entity_type, created_at, updated_at)"
        " VALUES (?, ?, ?, ?)",
        (name, entity_type, now, now),
    )
    return cur.lastrowid


def _seed_mention(conn, entity_id, chunk_id, run_id, surface="Someone"):
    cur = conn.execute(
        "INSERT INTO entity_mentions (entity_id, surface_form, chunk_id, extraction_run_id)"
        " VALUES (?, ?, ?, ?)",
        (entity_id, surface, chunk_id, run_id),
    )
    return cur.lastrowid


def _seed_relation(conn, subject_id, object_id, run_id, evidence_chunk_id, predicate="knows"):
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO relations (subject_id, predicate, object_id, evidence_chunk_id,"
        " extraction_run_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (subject_id, predicate, object_id, evidence_chunk_id, run_id, now),
    )
    return cur.lastrowid


def _counts(conn):
    tables = (
        "documents",
        "chunks",
        "entity_mentions",
        "relations",
        "entities",
        "vec_chunks",
        "vec_entity_mentions",
    )
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


@pytest.fixture
def graph_with_two_documents(db_conn):
    """Two documents, each with a chunk, a mention, a vector, and a relation.

    Returns the ids needed to assert that removing one leaves the other intact.
    """
    conn = db_conn
    run_id = _seed_extraction_run(conn)

    doomed_id, doomed_chunks = _seed_document(conn, "archive/old.md")
    kept_id, kept_chunks = _seed_document(conn, "notes/today.md")

    only_in_doomed = _seed_entity(conn, "Ghost")
    in_both = _seed_entity(conn, "Sarah Chen")

    doomed_mention = _seed_mention(conn, only_in_doomed, doomed_chunks[0], run_id)
    shared_mention = _seed_mention(conn, in_both, doomed_chunks[0], run_id)
    kept_mention = _seed_mention(conn, in_both, kept_chunks[0], run_id)

    doomed_relation = _seed_relation(
        conn, only_in_doomed, in_both, run_id, doomed_chunks[0], predicate="worked_with"
    )
    kept_relation = _seed_relation(
        conn, in_both, in_both, run_id, kept_chunks[0], predicate="self_ref"
    )

    for chunk_id in doomed_chunks + kept_chunks:
        conn.execute(
            "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
            (chunk_id, _vector()),
        )
    for mention_id in (doomed_mention, shared_mention, kept_mention):
        conn.execute(
            "INSERT INTO vec_entity_mentions (mention_id, embedding) VALUES (?, ?)",
            (mention_id, _vector()),
        )
    conn.commit()

    return {
        "conn": conn,
        "doomed_doc": doomed_id,
        "kept_doc": kept_id,
        "doomed_chunk": doomed_chunks[0],
        "kept_chunk": kept_chunks[0],
        "only_in_doomed": only_in_doomed,
        "in_both": in_both,
        "doomed_mention": doomed_mention,
        "kept_mention": kept_mention,
        "doomed_relation": doomed_relation,
        "kept_relation": kept_relation,
    }


# --------------------------------------------------------------------------------------
# Pruning (US2)
# --------------------------------------------------------------------------------------


def test_prune_removes_the_document_and_its_derived_rows(graph_with_two_documents):
    g = graph_with_two_documents
    conn = g["conn"]

    stats = prune_missing_documents(conn, {"notes/today.md"})

    assert stats["documents_removed"] == 1
    assert stats["chunks_removed"] == 1

    paths = [r[0] for r in conn.execute("SELECT path FROM documents").fetchall()]
    assert paths == ["notes/today.md"]
    assert (
        conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = ?", (g["doomed_doc"],)
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM entity_mentions WHERE chunk_id = ?", (g["doomed_chunk"],)
        ).fetchone()[0]
        == 0
    )

    # The surviving document keeps everything of its own.
    assert (
        conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = ?", (g["kept_doc"],)
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM entity_mentions WHERE id = ?", (g["kept_mention"],)
        ).fetchone()[0]
        == 1
    )


def test_prune_deletes_relations_whose_evidence_is_gone(graph_with_two_documents):
    """relations.evidence_chunk_id is ON DELETE SET NULL, so this must be explicit."""
    g = graph_with_two_documents
    conn = g["conn"]

    stats = prune_missing_documents(conn, {"notes/today.md"})

    assert stats["relations_removed"] == 1
    surviving = conn.execute("SELECT id, evidence_chunk_id FROM relations").fetchall()
    assert [r[0] for r in surviving] == [g["kept_relation"]]
    assert all(r[1] is not None for r in surviving), "no relation may survive with null evidence"


def test_prune_clears_stale_vectors(graph_with_two_documents):
    """A leftover vector row would bind to a reused id and poison later search.

    embed_new_chunks selects chunks WHERE id NOT IN (SELECT chunk_id FROM vec_chunks),
    and chunks.id is a plain INTEGER PRIMARY KEY, so ids are reused after deletes.
    """
    g = graph_with_two_documents
    conn = g["conn"]

    stats = prune_missing_documents(conn, {"notes/today.md"})

    assert (
        conn.execute(
            "SELECT count(*) FROM vec_chunks WHERE chunk_id = ?", (g["doomed_chunk"],)
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM vec_entity_mentions WHERE mention_id = ?", (g["doomed_mention"],)
        ).fetchone()[0]
        == 0
    )

    # The survivors' vectors are untouched.
    assert (
        conn.execute(
            "SELECT count(*) FROM vec_chunks WHERE chunk_id = ?", (g["kept_chunk"],)
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM vec_entity_mentions WHERE mention_id = ?", (g["kept_mention"],)
        ).fetchone()[0]
        == 1
    )

    # No vector row may outlive the row it describes.
    assert (
        conn.execute(
            "SELECT count(*) FROM vec_chunks WHERE chunk_id NOT IN (SELECT id FROM chunks)"
        ).fetchone()[0]
        == 0
    )
    # One chunk vector plus the two mention vectors on that chunk.
    assert stats["vectors_removed"] == 3


def test_prune_sweeps_only_entities_left_with_nothing(graph_with_two_documents):
    """An entity extracted only from a removed note must stop answering queries."""
    g = graph_with_two_documents
    conn = g["conn"]

    stats = prune_missing_documents(conn, {"notes/today.md"})

    names = [r[0] for r in conn.execute("SELECT canonical_name FROM entities").fetchall()]
    assert names == ["Sarah Chen"], "the entity mentioned only in the removed note should be gone"
    assert stats["entities_removed"] == 1


def test_prune_keeps_an_entity_that_still_holds_a_relation(db_conn):
    """No mentions left but still party to a relation: not an orphan, so not swept."""
    conn = db_conn
    run_id = _seed_extraction_run(conn)
    _, chunks = _seed_document(conn, "archive/old.md")
    _, kept_chunks = _seed_document(conn, "notes/today.md")

    lonely = _seed_entity(conn, "Lonely")
    anchor = _seed_entity(conn, "Anchor")
    _seed_mention(conn, lonely, chunks[0], run_id)
    _seed_mention(conn, anchor, kept_chunks[0], run_id)
    # Evidence lives in the surviving document, so this relation is not removed.
    _seed_relation(conn, lonely, anchor, run_id, kept_chunks[0])
    conn.commit()

    prune_missing_documents(conn, {"notes/today.md"})

    names = sorted(r[0] for r in conn.execute("SELECT canonical_name FROM entities").fetchall())
    assert names == ["Anchor", "Lonely"]


def test_prune_is_idempotent(graph_with_two_documents):
    """Re-running over an unchanged corpus removes nothing and reports nothing."""
    g = graph_with_two_documents
    conn = g["conn"]

    prune_missing_documents(conn, {"notes/today.md"})
    before = _counts(conn)
    watermark = conn.execute(
        "SELECT last_extracted_hash FROM documents WHERE path = 'notes/today.md'"
    ).fetchone()[0]

    stats = prune_missing_documents(conn, {"notes/today.md"})

    assert all(value == 0 for value in stats.values()), stats
    assert _counts(conn) == before
    assert (
        conn.execute(
            "SELECT last_extracted_hash FROM documents WHERE path = 'notes/today.md'"
        ).fetchone()[0]
        == watermark
    ), "pruning must not disturb the extraction watermark"


def test_prune_refuses_to_empty_the_graph(graph_with_two_documents):
    """A stray '*' pattern must not silently delete an entire corpus (FR-015)."""
    g = graph_with_two_documents
    conn = g["conn"]
    before = _counts(conn)

    with pytest.raises(RuntimeError, match="exclude every"):
        prune_missing_documents(conn, set())

    assert _counts(conn) == before, "the guard must fire before any write"


def test_prune_on_an_empty_graph_is_a_no_op(db_conn):
    """The guard is about protecting existing work, not about refusing empty corpora."""
    stats = prune_missing_documents(db_conn, set())
    assert stats["documents_removed"] == 0


# --------------------------------------------------------------------------------------
# Pruning through ingest_documents: deleted, renamed, and newly-ignored files (US2)
# --------------------------------------------------------------------------------------


def test_ingest_removes_a_deleted_file(initialized_corpus, db_conn):
    (initialized_corpus / "extra.md").write_text("# extra\n\nSome text.\n")
    ingest_documents(db_conn, initialized_corpus, {})
    assert _indexed_paths(db_conn) and "extra.md" in _indexed_paths(db_conn)

    (initialized_corpus / "extra.md").unlink()
    stats = ingest_documents(db_conn, initialized_corpus, {})

    assert stats["documents_removed"] == 1
    assert "extra.md" not in _indexed_paths(db_conn)


def test_ingest_treats_a_rename_as_one_removal_and_one_insert(initialized_corpus, db_conn):
    (initialized_corpus / "before.md").write_text("# note\n\nStable text.\n")
    ingest_documents(db_conn, initialized_corpus, {})

    (initialized_corpus / "before.md").rename(initialized_corpus / "after.md")
    stats = ingest_documents(db_conn, initialized_corpus, {})

    assert stats["documents_removed"] == 1
    assert stats["new"] == 1
    paths = _indexed_paths(db_conn)
    assert "after.md" in paths and "before.md" not in paths


def test_ingest_removes_a_newly_ignored_file(initialized_corpus, db_conn):
    """The case that makes .kgmdignore work for a corpus that already has a graph."""
    (initialized_corpus / "archive").mkdir()
    (initialized_corpus / "archive" / "old.md").write_text("# old\n\nSuperseded.\n")
    ingest_documents(db_conn, initialized_corpus, {})
    assert "archive/old.md" in _indexed_paths(db_conn)

    (initialized_corpus / ".kgmdignore").write_text("archive/\n")
    stats = ingest_documents(db_conn, initialized_corpus, {})

    assert stats["documents_removed"] == 1
    assert "archive/old.md" not in _indexed_paths(db_conn)
    assert conn_has_no_orphan_chunks(db_conn)


def test_ingest_is_idempotent_after_a_removal(initialized_corpus, db_conn):
    (initialized_corpus / "archive").mkdir()
    (initialized_corpus / "archive" / "old.md").write_text("# old\n\nSuperseded.\n")
    ingest_documents(db_conn, initialized_corpus, {})
    (initialized_corpus / ".kgmdignore").write_text("archive/\n")
    ingest_documents(db_conn, initialized_corpus, {})

    before = _counts(db_conn)
    stats = ingest_documents(db_conn, initialized_corpus, {})

    assert stats["documents_removed"] == 0
    assert stats["new"] == 0
    assert stats["updated"] == 0
    assert _counts(db_conn) == before


def test_ingest_refuses_to_empty_an_existing_graph(initialized_corpus, db_conn):
    ingest_documents(db_conn, initialized_corpus, {})
    before = _counts(db_conn)

    (initialized_corpus / ".kgmdignore").write_text("*\n")

    with pytest.raises(RuntimeError, match="exclude every"):
        ingest_documents(db_conn, initialized_corpus, {})

    assert _counts(db_conn) == before


def _indexed_paths(conn):
    return {r[0] for r in conn.execute("SELECT path FROM documents").fetchall()}


def conn_has_no_orphan_chunks(conn):
    orphans = conn.execute(
        "SELECT count(*) FROM chunks WHERE document_id NOT IN (SELECT id FROM documents)"
    ).fetchone()[0]
    stale_vectors = conn.execute(
        "SELECT count(*) FROM vec_chunks WHERE chunk_id NOT IN (SELECT id FROM chunks)"
    ).fetchone()[0]
    return orphans == 0 and stale_vectors == 0


# --------------------------------------------------------------------------------------
# Dry-run report (US3)
# --------------------------------------------------------------------------------------


def test_dry_run_report_shape_and_paths(initialized_corpus, db_conn):
    (initialized_corpus / "archive").mkdir()
    (initialized_corpus / "archive" / "old.md").write_text("# old\n")
    (initialized_corpus / ".kgmd" / "notes.md").write_text("# hidden\n")
    (initialized_corpus / ".kgmdignore").write_text("archive/\n")

    report = dry_run_report(db_conn, initialized_corpus, {})

    assert set(report) == {"included", "ignored", "dotpath", "counts"}
    assert set(report["counts"]) == {"included", "ignored", "dotpath", "would_remove"}
    assert report["ignored"] == ["archive/old.md"]
    assert ".kgmd/notes.md" in report["dotpath"]
    assert report["counts"]["included"] == len(report["included"])
    assert report["included"] == sorted(report["included"])
    assert all(not p.startswith("/") for p in report["included"]), "paths must be corpus-relative"


def test_dry_run_report_counts_pending_removals(initialized_corpus, db_conn):
    (initialized_corpus / "archive").mkdir()
    (initialized_corpus / "archive" / "old.md").write_text("# old\n\nSuperseded.\n")
    ingest_documents(db_conn, initialized_corpus, {})
    (initialized_corpus / ".kgmdignore").write_text("archive/\n")

    report = dry_run_report(db_conn, initialized_corpus, {})

    assert report["counts"]["would_remove"] == 1
    assert "archive/old.md" not in report["included"]


def test_dry_run_report_writes_nothing(initialized_corpus, db_conn):
    ingest_documents(db_conn, initialized_corpus, {})
    (initialized_corpus / ".kgmdignore").write_text("*\n")
    before = _counts(db_conn)

    # Even the case that a real build refuses is only reported, never acted on.
    report = dry_run_report(db_conn, initialized_corpus, {})

    assert report["included"] == []
    assert _counts(db_conn) == before


def test_dry_run_report_without_a_database(tmp_corpus):
    report = dry_run_report(None, tmp_corpus, {})
    assert report["counts"]["would_remove"] == 0
    assert report["counts"]["included"] > 0
