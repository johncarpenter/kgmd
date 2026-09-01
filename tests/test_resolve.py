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
        "INSERT INTO extraction_runs (started_at, model, status) VALUES (?, 'test', 'completed')",
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
        "INSERT INTO extraction_runs (started_at, model, status) VALUES (?, 'test', 'completed')",
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
        "SELECT COUNT(*) FROM relations"
        " WHERE subject_id = 1 AND predicate = 'runs' AND object_id = 3"
    ).fetchone()[0]
    assert survivor_rel == 1

    conn.close()


def test_resolution_merge_count_excludes_skipped_cluster(initialized_corpus):
    """The reported merge count must not include a cluster that was skipped.

    The mentions list is read once at the start of the run, so a later cluster
    can name a survivor_id an earlier cluster already deleted. _merge_entities
    skips that cluster; the count run_resolution persists and returns has to
    skip it too, or resolution_runs.merges overstates what happened.
    """
    from kgmd.config import load_config
    from kgmd.db import get_connection

    db_path = initialized_corpus / ".kgmd" / "graph.db"
    conn = get_connection(db_path)
    config = load_config(initialized_corpus)
    config["resolution"]["llm_verify_clusters"] = False
    now = datetime.now(timezone.utc).isoformat()

    _seed_run_doc_chunk(conn, now)

    # Three entities of the same type. Entity 2 carries two mentions, one
    # matching entity 1 and one matching entity 3, so union-find produces two
    # separate clusters: {1, 2} and {2, 3}.
    conn.execute(SQL_INSERT_ENTITY, ("Brian Anderson", "Person", now, now))
    conn.execute(SQL_INSERT_ENTITY, ("B. Anderson", "Person", now, now))
    conn.execute(SQL_INSERT_ENTITY, ("Bri Anderson", "Person", now, now))

    dim = 384
    vec_a = [0.0] * dim
    vec_a[0] = 1.0
    vec_b = [0.0] * dim
    vec_b[1] = 1.0  # orthogonal to vec_a -> cosine similarity 0

    mentions = [
        (1, "Brian Anderson", vec_a),
        (2, "B. Anderson", vec_a),
        (2, "B Anderson", vec_b),
        (3, "Bri Anderson", vec_b),
    ]
    for mention_id, (entity_id, surface, vec) in enumerate(mentions, start=1):
        conn.execute(SQL_INSERT_MENTION, (entity_id, surface))
        conn.execute(
            "INSERT INTO vec_entity_mentions (mention_id, embedding) VALUES (?, ?)",
            (mention_id, struct.pack(f"{dim}f", *vec)),
        )
    conn.commit()

    stats = run_resolution(conn, config)

    # Only the first cluster merges: entity 2 folds into entity 1. The second
    # cluster names survivor_id 2, which no longer exists, so it is skipped and
    # entity 3 survives.
    remaining = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    assert remaining == 2
    assert stats["merges"] == 1

    persisted = conn.execute(
        "SELECT merges FROM resolution_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    assert persisted == 1

    conn.close()


def test_resolution_merge_count_excludes_already_deleted_drop(initialized_corpus):
    """A drop entity an earlier cluster already deleted must not be counted.

    The mirror of the stale-survivor case: here the survivor is still present,
    so the merge runs, but one of its drop_ids was deleted by an earlier
    cluster. Re-pointing and deleting that id are no-ops, so it must not be
    counted as a merge.
    """
    from kgmd.config import load_config
    from kgmd.db import get_connection

    db_path = initialized_corpus / ".kgmd" / "graph.db"
    conn = get_connection(db_path)
    config = load_config(initialized_corpus)
    config["resolution"]["llm_verify_clusters"] = False
    now = datetime.now(timezone.utc).isoformat()

    _seed_run_doc_chunk(conn, now)

    # Entity 3 is shared between two clusters: {2, 3} and {1, 3}. The first
    # deletes entity 3 as a drop; the second still names it as a drop under a
    # survivor (entity 1) that is very much alive.
    conn.execute(SQL_INSERT_ENTITY, ("Brian Anderson", "Person", now, now))
    conn.execute(SQL_INSERT_ENTITY, ("Bri Anderson", "Person", now, now))
    conn.execute(SQL_INSERT_ENTITY, ("B. Anderson", "Person", now, now))

    dim = 384
    vec_a = [0.0] * dim
    vec_a[0] = 1.0
    vec_b = [0.0] * dim
    vec_b[1] = 1.0

    mentions = [
        (2, "Bri Anderson", vec_a),
        (3, "B. Anderson", vec_a),
        (3, "B Anderson", vec_b),
        (1, "Brian Anderson", vec_b),
    ]
    for mention_id, (entity_id, surface, vec) in enumerate(mentions, start=1):
        conn.execute(SQL_INSERT_MENTION, (entity_id, surface))
        conn.execute(
            "INSERT INTO vec_entity_mentions (mention_id, embedding) VALUES (?, ?)",
            (mention_id, struct.pack(f"{dim}f", *vec)),
        )
    conn.commit()

    stats = run_resolution(conn, config)

    remaining = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    assert stats["merges"] == 3 - remaining

    conn.close()
