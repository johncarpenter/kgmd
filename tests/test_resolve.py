"""Tests for entity resolution with mocked LLM."""

import struct
from datetime import datetime, timezone

from kgmd.resolve import _cosine_similarity, _merge_entities, run_resolution

SQL_INSERT_DOC = (
    "INSERT INTO documents (path, content_hash, size_bytes, mtime, ingested_at)"
    " VALUES (?, ?, ?, ?, ?)"
)
SQL_INSERT_CHUNK = (
    "INSERT INTO chunks"
    " (document_id, chunk_index, content, char_start, char_end)"
    " VALUES (1, 0, 'test', 0, 4)"
)
SQL_INSERT_ENTITY = (
    "INSERT INTO entities"
    " (canonical_name, entity_type, attributes, created_at, updated_at)"
    " VALUES (?, ?, '{}', ?, ?)"
)
SQL_INSERT_MENTION = (
    "INSERT INTO entity_mentions"
    " (entity_id, surface_form, chunk_id, extraction_run_id, confidence)"
    " VALUES (?, ?, 1, 1, 0.9)"
)


def test_cosine_similarity():
    """Test cosine similarity computation."""
    a = (1.0, 0.0, 0.0)
    b = (1.0, 0.0, 0.0)
    assert abs(_cosine_similarity(a, b) - 1.0) < 1e-6

    c = (0.0, 1.0, 0.0)
    assert abs(_cosine_similarity(a, c)) < 1e-6

    d = (-1.0, 0.0, 0.0)
    assert abs(_cosine_similarity(a, d) - (-1.0)) < 1e-6


def test_resolution_no_mentions(initialized_corpus):
    """Test resolution with no mentions returns 0 merges."""
    from kgmd.config import load_config
    from kgmd.db import get_connection

    db_path = initialized_corpus / ".kgmd" / "graph.db"
    conn = get_connection(db_path)
    config = load_config(initialized_corpus)

    stats = run_resolution(conn, config)
    assert stats["merges"] == 0
    conn.close()


def test_resolution_merges_duplicates(initialized_corpus):
    """Test resolution merges entities with similar embeddings."""
    from kgmd.config import load_config
    from kgmd.db import get_connection

    db_path = initialized_corpus / ".kgmd" / "graph.db"
    conn = get_connection(db_path)
    config = load_config(initialized_corpus)
    config["resolution"]["llm_verify_clusters"] = False
    now = datetime.now(timezone.utc).isoformat()

    # Insert a document and chunk
    conn.execute(SQL_INSERT_DOC, ("test.md", "abc", 10, 0.0, now))
    conn.execute(SQL_INSERT_CHUNK)
    conn.execute(
        "INSERT INTO extraction_runs"
        " (started_at, model, status) VALUES (?, 'test', 'completed')",
        (now,),
    )

    # Insert two entities that are duplicates
    conn.execute(SQL_INSERT_ENTITY, ("Brian Anderson", "Person", now, now))
    conn.execute(SQL_INSERT_ENTITY, ("B. Anderson", "Person", now, now))

    # Insert mentions with very similar embeddings
    dim = 384
    vec1 = [0.1] * dim
    vec2 = [0.1] * dim  # Identical -> cosine sim = 1.0
    vec_bytes1 = struct.pack(f"{dim}f", *vec1)
    vec_bytes2 = struct.pack(f"{dim}f", *vec2)

    conn.execute(SQL_INSERT_MENTION, (1, "Brian Anderson"))
    conn.execute(SQL_INSERT_MENTION, (2, "B. Anderson"))
    conn.execute(
        "INSERT INTO vec_entity_mentions (mention_id, embedding) VALUES (1, ?)",
        (vec_bytes1,),
    )
    conn.execute(
        "INSERT INTO vec_entity_mentions (mention_id, embedding) VALUES (2, ?)",
        (vec_bytes2,),
    )
    conn.commit()

    stats = run_resolution(conn, config)
    assert stats["merges"] == 1

    # Should have only 1 entity left
    count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    assert count == 1

    conn.close()


SQL_INSERT_RELATION = (
    "INSERT INTO relations"
    " (subject_id, predicate, object_id, evidence_chunk_id,"
    " extraction_run_id, confidence, created_at)"
    " VALUES (?, ?, ?, ?, 1, 0.9, ?)"
)


def _seed_run_doc_chunk(conn, now):
    """Insert a document, chunk and extraction run so relations can be added."""
    conn.execute(SQL_INSERT_DOC, ("test.md", "abc", 10, 0.0, now))
    conn.execute(SQL_INSERT_CHUNK)
    conn.execute(
        "INSERT INTO extraction_runs"
        " (started_at, model, status) VALUES (?, 'test', 'completed')",
        (now,),
    )


def test_merge_entities_stale_survivor(initialized_corpus):
    """Case A: a cluster naming an already-deleted survivor_id is skipped.

    During a single run_resolution pass the mentions list is read once up
    front, so a later cluster can name a survivor_id an earlier cluster already
    merged away. The survivor-row SELECT then returns None; _merge_entities must
    return without raising rather than crash on None["attributes"].
    """
    from kgmd.db import get_connection

    db_path = initialized_corpus / ".kgmd" / "graph.db"
    conn = get_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()

    _seed_run_doc_chunk(conn, now)
    conn.execute(SQL_INSERT_ENTITY, ("Brian Anderson", "Person", now, now))
    conn.execute(SQL_INSERT_ENTITY, ("B. Anderson", "Person", now, now))
    conn.commit()

    # Simulate an earlier cluster having already deleted the survivor.
    conn.execute("DELETE FROM entities WHERE id = 1")
    conn.commit()

    # Must not raise — the survivor is gone, so this cluster is skipped.
    _merge_entities(conn, survivor_id=1, drop_ids=[2], canonical_name="Brian Anderson")

    # Drop entity is untouched; nothing crashed.
    count = conn.execute("SELECT COUNT(*) FROM entities WHERE id = 2").fetchone()[0]
    assert count == 1

    conn.close()


def test_merge_entities_relation_unique_collision(initialized_corpus):
    """Case B: re-pointing relations onto the survivor can hit the UNIQUE index.

    The unique index on (subject_id, predicate, object_id, evidence_chunk_id)
    fires when a dropped entity has a relation whose re-pointed tuple already
    exists for the survivor. _merge_entities must not raise IntegrityError, and
    no relation may reference a dropped id afterward.
    """
    from kgmd.db import get_connection

    db_path = initialized_corpus / ".kgmd" / "graph.db"
    conn = get_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()

    _seed_run_doc_chunk(conn, now)
    # 1 = survivor, 2 = drop, 3 = shared object
    conn.execute(SQL_INSERT_ENTITY, ("Acme Corp", "Organization", now, now))
    conn.execute(SQL_INSERT_ENTITY, ("ACME", "Organization", now, now))
    conn.execute(SQL_INSERT_ENTITY, ("Digital Transformation", "Project", now, now))

    # Two relations that collide once the drop's subject_id is re-pointed to 1.
    conn.execute(SQL_INSERT_RELATION, (1, "runs", 3, 1, now))
    conn.execute(SQL_INSERT_RELATION, (2, "runs", 3, 1, now))
    conn.commit()

    # Must not raise sqlite3.IntegrityError.
    _merge_entities(conn, survivor_id=1, drop_ids=[2], canonical_name="Acme Corp")

    # No relation should still reference the dropped id.
    dangling = conn.execute(
        "SELECT COUNT(*) FROM relations WHERE subject_id = 2 OR object_id = 2"
    ).fetchone()[0]
    assert dangling == 0

    # The surviving relation is preserved.
    survivor_rel = conn.execute(
        "SELECT COUNT(*) FROM relations WHERE subject_id = 1 AND predicate = 'runs' AND object_id = 3"
    ).fetchone()[0]
    assert survivor_rel == 1

    conn.close()
