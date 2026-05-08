"""Tests for MCP tool invocations against a seeded fixture database."""

import struct

from kgmd.query import (
    find_path,
    get_current_schema,
    get_entity,
    get_neighbors,
    list_entities,
    list_relations,
    search_chunks,
)


def test_mcp_list_entities(seeded_db):
    """Test the query layer that backs the MCP list_entities tool."""
    results = list_entities(seeded_db, entity_type="Person")
    assert len(results) == 2
    assert all(r["type"] == "Person" for r in results)


def test_mcp_get_entity(seeded_db):
    """Test the query layer that backs the MCP get_entity tool."""
    result = get_entity(seeded_db, "Sarah Chen")
    assert result is not None
    assert result["type"] == "Person"
    assert len(result["outgoing_relations"]) >= 1


def test_mcp_get_neighbors(seeded_db):
    """Test the query layer that backs the MCP get_neighbors tool."""
    result = get_neighbors(seeded_db, "Acme Corp", depth=1)
    assert len(result["nodes"]) >= 1


def test_mcp_find_path(seeded_db):
    """Test the query layer that backs the MCP find_path tool."""
    result = find_path(seeded_db, "Brian Anderson", "Acme Corp")
    assert result is not None


def test_mcp_list_relations(seeded_db):
    """Test the query layer that backs the MCP list_relations tool."""
    results = list_relations(seeded_db, predicate="works_at")
    assert len(results) == 2


def test_mcp_get_schema_empty(seeded_db):
    """Test get_schema when no schema exists."""
    result = get_current_schema(seeded_db)
    assert result is None


def test_mcp_search(seeded_db):
    """Test the query layer that backs the MCP search tool."""
    # Add embeddings for chunks
    dim = 384
    vec = [0.5] * dim
    vec_bytes = struct.pack(f"{dim}f", *vec)

    chunks = seeded_db.execute("SELECT id FROM chunks").fetchall()
    for chunk in chunks:
        seeded_db.execute(
            "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
            (chunk["id"], vec_bytes),
        )
    seeded_db.commit()

    results = search_chunks(seeded_db, vec, limit=5)
    assert len(results) >= 1
    assert "chunk_text" in results[0]
    assert "entities" in results[0]
