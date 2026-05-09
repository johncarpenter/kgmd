"""Tests for entity resolution with mocked LLM."""

import struct
from datetime import datetime, timezone

from kgmd.resolve import _cosine_similarity, run_resolution

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
