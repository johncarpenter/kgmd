"""MCP stdio server exposing the knowledge graph."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from kgmd.db import get_connection
from kgmd.query import (
    find_path,
    get_current_schema,
    get_entity,
    get_neighbors,
    list_entities,
    list_relations,
    search_chunks,
)

mcp = FastMCP(
    "kgmd",
    instructions="Local knowledge graph over your markdown corpus.",
)


def _get_conn():
    """Get a database connection from .kgmd/graph.db in cwd."""
    db_path = Path.cwd() / ".kgmd" / "graph.db"
    if not db_path.exists():
        raise FileNotFoundError(
            f"No kgmd database found at {db_path}. Run 'kgmd init' and 'kgmd build' first."
        )
    return get_connection(db_path)


def _get_config():
    """Load config from cwd corpus."""
    from kgmd.config import load_config

    return load_config(Path.cwd())


@mcp.tool()
def search(query: str, limit: int = 10) -> list[dict]:
    """Semantic search over the markdown corpus. Returns matching chunks with entities."""
    conn = _get_conn()
    config = _get_config()

    from kgmd.embed import get_embedder

    embedder = get_embedder(config)
    query_vec = embedder.embed([query])[0]

    results = search_chunks(conn, query_vec, limit)
    conn.close()

    return [
        {
            "chunk_text": r["chunk_text"],
            "document_path": r["document_path"],
            "entities": r["entities"],
        }
        for r in results
    ]


@mcp.tool()
def get_entity_tool(name: str, type: str | None = None) -> dict | str:
    """Get full entity record including attributes, mentions, and relations."""
    conn = _get_conn()
    result = get_entity(conn, name, type)
    conn.close()
    if not result:
        return f"Entity '{name}' not found."
    return result


@mcp.tool()
def list_entities_tool(type: str | None = None, limit: int = 50) -> list[dict]:
    """List entities, optionally filtered by type."""
    conn = _get_conn()
    results = list_entities(conn, entity_type=type, limit=limit)
    conn.close()
    return results


@mcp.tool()
def get_neighbors_tool(name: str, depth: int = 1) -> dict:
    """Get the subgraph around an entity up to a given depth."""
    conn = _get_conn()
    result = get_neighbors(conn, name, depth)
    conn.close()
    return result


@mcp.tool()
def find_path_tool(from_name: str, to_name: str, max_depth: int = 5) -> list[dict] | str:
    """Find the shortest path between two entities."""
    conn = _get_conn()
    result = find_path(conn, from_name, to_name, max_depth)
    conn.close()
    if result is None:
        return f"No path found between '{from_name}' and '{to_name}'."
    return result


@mcp.tool()
def list_relations_tool(
    predicate: str | None = None,
    subject: str | None = None,
    object: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List relations with optional filters."""
    conn = _get_conn()
    results = list_relations(
        conn, predicate=predicate, subject=subject, object_name=object, limit=limit
    )
    conn.close()
    return results


@mcp.tool()
def get_schema_tool() -> dict | str:
    """Get the current induced schema."""
    conn = _get_conn()
    result = get_current_schema(conn)
    conn.close()
    if not result:
        return "No schema has been induced yet."
    return result


def run_server():
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")
