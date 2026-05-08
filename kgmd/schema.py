"""SQL DDL and Pydantic models for the knowledge graph."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# SQL DDL
# ---------------------------------------------------------------------------

SCHEMA_SQL = """\
-- Key-value store for metadata (embedding dim, model, schema version).
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Source markdown files.
CREATE TABLE IF NOT EXISTS documents (
    id                  INTEGER PRIMARY KEY,
    path                TEXT NOT NULL UNIQUE,
    content_hash        TEXT NOT NULL,
    size_bytes          INTEGER NOT NULL,
    mtime               REAL NOT NULL,
    ingested_at         TEXT NOT NULL,
    last_extracted_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);

-- Chunks of documents.
CREATE TABLE IF NOT EXISTS chunks (
    id            INTEGER PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    content       TEXT NOT NULL,
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    token_count   INTEGER,
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);

-- Tracking table for extraction runs.
CREATE TABLE IF NOT EXISTS extraction_runs (
    id                   INTEGER PRIMARY KEY,
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    model                TEXT NOT NULL,
    status               TEXT NOT NULL,
    documents_processed  INTEGER NOT NULL DEFAULT 0,
    error_message        TEXT
);

-- Canonical entities.
CREATE TABLE IF NOT EXISTS entities (
    id              INTEGER PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    attributes      TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(canonical_name, entity_type)
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name);

-- Surface forms / mentions.
CREATE TABLE IF NOT EXISTS entity_mentions (
    id                INTEGER PRIMARY KEY,
    entity_id         INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    surface_form      TEXT NOT NULL,
    chunk_id          INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    char_start        INTEGER,
    char_end          INTEGER,
    extraction_run_id INTEGER NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    confidence        REAL
);

CREATE INDEX IF NOT EXISTS idx_mentions_entity  ON entity_mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_mentions_chunk   ON entity_mentions(chunk_id);
CREATE INDEX IF NOT EXISTS idx_mentions_surface ON entity_mentions(surface_form);

-- Relations between entities (directed).
CREATE TABLE IF NOT EXISTS relations (
    id                INTEGER PRIMARY KEY,
    subject_id        INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    predicate         TEXT NOT NULL,
    object_id         INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    evidence_chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
    extraction_run_id INTEGER NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    confidence        REAL,
    attributes        TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_relations_subject   ON relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_relations_object     ON relations(object_id);
CREATE INDEX IF NOT EXISTS idx_relations_predicate  ON relations(predicate);
CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_unique
    ON relations(subject_id, predicate, object_id, evidence_chunk_id);

-- Tracking for resolution runs.
CREATE TABLE IF NOT EXISTS resolution_runs (
    id                   INTEGER PRIMARY KEY,
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    embedding_model      TEXT NOT NULL,
    llm_model            TEXT NOT NULL,
    similarity_threshold REAL NOT NULL,
    merges               INTEGER NOT NULL DEFAULT 0,
    status               TEXT NOT NULL
);

-- Versioned induced schemas.
CREATE TABLE IF NOT EXISTS schema_versions (
    id                  INTEGER PRIMARY KEY,
    created_at          TEXT NOT NULL,
    llm_model           TEXT NOT NULL,
    schema_yaml         TEXT NOT NULL,
    entity_type_count   INTEGER NOT NULL,
    relation_type_count INTEGER NOT NULL,
    notes               TEXT
);

CREATE VIEW IF NOT EXISTS current_schema AS
    SELECT * FROM schema_versions ORDER BY id DESC LIMIT 1;
"""


def vec_tables_sql(dim: int) -> str:
    """Return DDL for sqlite-vec virtual tables with the given dimension."""
    return f"""\
CREATE VIRTUAL TABLE IF NOT EXISTS vec_entity_mentions USING vec0(
    mention_id INTEGER PRIMARY KEY,
    embedding FLOAT[{dim}]
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding FLOAT[{dim}]
);
"""


KV_DEFAULTS = {
    "embedding_dim": "384",
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "schema_version": "1",
}


# ---------------------------------------------------------------------------
# Pydantic models for LLM extraction output
# ---------------------------------------------------------------------------


class ExtractedEntity(BaseModel):
    surface_form: str
    canonical_name: str
    entity_type: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    char_start: int | None = None
    char_end: int | None = None
    confidence: float | None = None


class ExtractedRelation(BaseModel):
    subject: str
    predicate: str
    object: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]


# ---------------------------------------------------------------------------
# Pydantic models for LLM resolution output
# ---------------------------------------------------------------------------


class ResolvedCluster(BaseModel):
    canonical_name: str
    members: list[str]


class ResolutionResult(BaseModel):
    same_entity: bool
    partitions: list[ResolvedCluster] = Field(default_factory=list)
