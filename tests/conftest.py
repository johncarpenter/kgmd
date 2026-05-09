"""Shared fixtures for kgmd tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kgmd.db import get_connection, init_db

FIXTURES_DIR = Path(__file__).parent / "fixtures"

SQL_INSERT_DOC = (
    "INSERT INTO documents (path, content_hash, size_bytes, mtime, ingested_at)"
    " VALUES (?, ?, ?, ?, ?)"
)
SQL_INSERT_CHUNK = (
    "INSERT INTO chunks"
    " (document_id, chunk_index, content, char_start, char_end, token_count)"
    " VALUES (?, ?, ?, ?, ?, ?)"
)
SQL_INSERT_ENTITY = (
    "INSERT INTO entities"
    " (canonical_name, entity_type, attributes, created_at, updated_at)"
    " VALUES (?, ?, ?, ?, ?)"
)
SQL_INSERT_MENTION = (
    "INSERT INTO entity_mentions"
    " (entity_id, surface_form, chunk_id, extraction_run_id, confidence)"
    " VALUES (?, ?, ?, ?, ?)"
)
SQL_INSERT_RUN = (
    "INSERT INTO extraction_runs"
    " (started_at, model, status, documents_processed)"
    " VALUES (?, ?, 'completed', 1)"
)
SQL_INSERT_RELATION = (
    "INSERT INTO relations"
    " (subject_id, predicate, object_id, evidence_chunk_id,"
    " extraction_run_id, confidence, created_at)"
    " VALUES (?, ?, ?, ?, ?, ?, ?)"
)


@pytest.fixture
def tmp_corpus(tmp_path):
    """Create a temporary corpus directory with fixtures copied in."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    # Copy fixture files
    for f in FIXTURES_DIR.glob("*.md"):
        (corpus / f.name).write_text(f.read_text())

    return corpus


@pytest.fixture
def initialized_corpus(tmp_corpus):
    """A corpus with .kgmd/ initialized."""
    kgmd_dir = tmp_corpus / ".kgmd"
    kgmd_dir.mkdir()
    (kgmd_dir / "logs").mkdir()
    (kgmd_dir / "prompts").mkdir()

    from kgmd.config import write_default_config

    write_default_config(kgmd_dir / "config.yaml")

    db_path = kgmd_dir / "graph.db"
    conn = init_db(db_path)
    conn.close()

    return tmp_corpus


@pytest.fixture
def db_conn(initialized_corpus):
    """A database connection for the initialized corpus."""
    db_path = initialized_corpus / ".kgmd" / "graph.db"
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def seeded_db(initialized_corpus):
    """A database seeded with entities and relations for query tests."""
    db_path = initialized_corpus / ".kgmd" / "graph.db"
    conn = get_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()

    # Insert documents
    conn.execute(SQL_INSERT_DOC, ("test.md", "abc123", 100, 1234567890.0, now))
    doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Insert chunks
    conn.execute(
        SQL_INSERT_CHUNK,
        (doc_id, 0, "Brian Anderson is the CFO of CFO Centre Canada.", 0, 49, 12),
    )
    chunk_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute(
        SQL_INSERT_CHUNK,
        (doc_id, 1, "Sarah Chen works at Acme Corp as a software engineer.", 50, 103, 13),
    )
    chunk_id2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Create extraction run
    conn.execute(SQL_INSERT_RUN, (now, "test-model"))
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Insert entities
    entities = [
        ("Brian Anderson", "Person", json.dumps({"role": "CFO"})),
        ("CFO Centre Canada", "Organization", json.dumps({})),
        ("Sarah Chen", "Person", json.dumps({"role": "Software Engineer"})),
        ("Acme Corp", "Organization", json.dumps({"industry": "Technology"})),
        ("Digital Transformation", "Project", json.dumps({})),
    ]
    entity_ids = {}
    for name, etype, attrs in entities:
        conn.execute(SQL_INSERT_ENTITY, (name, etype, attrs, now, now))
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        entity_ids[name] = eid

    # Insert mentions
    for name in ["Brian Anderson", "CFO Centre Canada"]:
        conn.execute(
            SQL_INSERT_MENTION,
            (entity_ids[name], name, chunk_id, run_id, 0.95),
        )

    for name in ["Sarah Chen", "Acme Corp"]:
        conn.execute(
            SQL_INSERT_MENTION,
            (entity_ids[name], name, chunk_id2, run_id, 0.9),
        )

    # Insert relations
    relations = [
        (entity_ids["Brian Anderson"], "works_at", entity_ids["CFO Centre Canada"], chunk_id),
        (entity_ids["Sarah Chen"], "works_at", entity_ids["Acme Corp"], chunk_id2),
        (entity_ids["Brian Anderson"], "leads", entity_ids["Digital Transformation"], chunk_id),
        (entity_ids["Acme Corp"], "runs", entity_ids["Digital Transformation"], chunk_id2),
    ]
    for sub, pred, obj, ck in relations:
        conn.execute(SQL_INSERT_RELATION, (sub, pred, obj, ck, run_id, 0.9, now))

    conn.commit()
    yield conn
    conn.close()
