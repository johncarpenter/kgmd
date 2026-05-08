"""Graph queries: entities, relations, neighbors, paths, semantic search."""

from __future__ import annotations

import json
import struct

import networkx as nx


def search_chunks(conn, query_vec: list[float], limit: int = 10) -> list[dict]:
    """Semantic search over chunks using vec_chunks."""
    vec_bytes = struct.pack(f"{len(query_vec)}f", *query_vec)
    rows = conn.execute(
        """SELECT c.id, c.content, c.char_start, c.char_end,
                  d.path, v.distance
           FROM vec_chunks v
           JOIN chunks c ON c.id = v.chunk_id
           JOIN documents d ON d.id = c.document_id
           WHERE v.embedding MATCH ?
           AND k = ?
           ORDER BY v.distance""",
        (vec_bytes, limit),
    ).fetchall()

    results = []
    for r in rows:
        # Find entities mentioned in this chunk
        entities = conn.execute(
            """SELECT DISTINCT e.canonical_name, e.entity_type
               FROM entity_mentions em
               JOIN entities e ON e.id = em.entity_id
               WHERE em.chunk_id = ?""",
            (r["id"],),
        ).fetchall()

        results.append(
            {
                "chunk_id": r["id"],
                "chunk_text": r["content"],
                "char_start": r["char_start"],
                "char_end": r["char_end"],
                "document_path": r["path"],
                "distance": r["distance"],
                "entities": [
                    {"name": e["canonical_name"], "type": e["entity_type"]} for e in entities
                ],
            }
        )
    return results


def list_entities(
    conn, entity_type: str | None = None, search: str | None = None, limit: int = 50
) -> list[dict]:
    """List entities, optionally filtered."""
    query = "SELECT id, canonical_name, entity_type, attributes FROM entities"
    params: list = []
    conditions = []

    if entity_type:
        conditions.append("entity_type = ?")
        params.append(entity_type)
    if search:
        conditions.append("canonical_name LIKE ?")
        params.append(f"%{search}%")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY canonical_name LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["canonical_name"],
            "type": r["entity_type"],
            "attributes": json.loads(r["attributes"]),
        }
        for r in rows
    ]


def get_entity(conn, name: str, entity_type: str | None = None) -> dict | None:
    """Get full entity record with mentions and relations."""
    query = "SELECT * FROM entities WHERE canonical_name = ?"
    params: list = [name]
    if entity_type:
        query += " AND entity_type = ?"
        params.append(entity_type)

    row = conn.execute(query, params).fetchone()
    if not row:
        return None

    eid = row["id"]

    # Mentions
    mentions = conn.execute(
        """SELECT em.surface_form, em.confidence, c.content as chunk_text, d.path
           FROM entity_mentions em
           JOIN chunks c ON c.id = em.chunk_id
           JOIN documents d ON d.id = c.document_id
           WHERE em.entity_id = ?""",
        (eid,),
    ).fetchall()

    # Outgoing relations
    outgoing = conn.execute(
        """SELECT r.predicate, e.canonical_name as object_name, e.entity_type as object_type,
                  r.confidence, r.attributes
           FROM relations r
           JOIN entities e ON e.id = r.object_id
           WHERE r.subject_id = ?""",
        (eid,),
    ).fetchall()

    # Incoming relations
    incoming = conn.execute(
        """SELECT r.predicate, e.canonical_name as subject_name, e.entity_type as subject_type,
                  r.confidence, r.attributes
           FROM relations r
           JOIN entities e ON e.id = r.subject_id
           WHERE r.object_id = ?""",
        (eid,),
    ).fetchall()

    return {
        "id": eid,
        "name": row["canonical_name"],
        "type": row["entity_type"],
        "attributes": json.loads(row["attributes"]),
        "mentions": [
            {
                "surface_form": m["surface_form"],
                "confidence": m["confidence"],
                "document": m["path"],
                "chunk_text": m["chunk_text"][:200],
            }
            for m in mentions
        ],
        "outgoing_relations": [
            {
                "predicate": r["predicate"],
                "object": r["object_name"],
                "object_type": r["object_type"],
                "confidence": r["confidence"],
                "attributes": json.loads(r["attributes"]),
            }
            for r in outgoing
        ],
        "incoming_relations": [
            {
                "predicate": r["predicate"],
                "subject": r["subject_name"],
                "subject_type": r["subject_type"],
                "confidence": r["confidence"],
                "attributes": json.loads(r["attributes"]),
            }
            for r in incoming
        ],
    }


def list_relations(
    conn,
    predicate: str | None = None,
    subject: str | None = None,
    object_name: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List relations with optional filters."""
    query = """SELECT r.id, r.predicate, r.confidence, r.attributes,
                      s.canonical_name as subject_name, s.entity_type as subject_type,
                      o.canonical_name as object_name, o.entity_type as object_type
               FROM relations r
               JOIN entities s ON s.id = r.subject_id
               JOIN entities o ON o.id = r.object_id"""
    params: list = []
    conditions = []

    if predicate:
        conditions.append("r.predicate = ?")
        params.append(predicate)
    if subject:
        conditions.append("s.canonical_name = ?")
        params.append(subject)
    if object_name:
        conditions.append("o.canonical_name = ?")
        params.append(object_name)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [
        {
            "id": r["id"],
            "subject": r["subject_name"],
            "subject_type": r["subject_type"],
            "predicate": r["predicate"],
            "object": r["object_name"],
            "object_type": r["object_type"],
            "confidence": r["confidence"],
            "attributes": json.loads(r["attributes"]),
        }
        for r in rows
    ]


def _build_graph(conn) -> nx.DiGraph:
    """Build a NetworkX directed graph from the database."""
    G = nx.DiGraph()

    # Add entity nodes
    entities = conn.execute(
        "SELECT id, canonical_name, entity_type, attributes FROM entities"
    ).fetchall()
    for e in entities:
        G.add_node(
            e["canonical_name"],
            entity_id=e["id"],
            entity_type=e["entity_type"],
            attributes=json.loads(e["attributes"]),
        )

    # Add relation edges
    relations = conn.execute(
        """SELECT s.canonical_name as subject, r.predicate, o.canonical_name as object,
                  r.confidence, r.attributes
           FROM relations r
           JOIN entities s ON s.id = r.subject_id
           JOIN entities o ON o.id = r.object_id"""
    ).fetchall()
    for r in relations:
        G.add_edge(
            r["subject"],
            r["object"],
            predicate=r["predicate"],
            confidence=r["confidence"],
            attributes=json.loads(r["attributes"]),
        )

    return G


def get_neighbors(conn, name: str, depth: int = 1, entity_type: str | None = None) -> dict:
    """Get subgraph around an entity up to depth N."""
    G = _build_graph(conn)
    if name not in G:
        return {"nodes": [], "edges": []}

    # BFS to collect nodes within depth
    visited = {name}
    frontier = {name}
    for _ in range(depth):
        next_frontier = set()
        for node in frontier:
            for neighbor in set(G.successors(node)) | set(G.predecessors(node)):
                if neighbor not in visited:
                    if entity_type and G.nodes[neighbor].get("entity_type") != entity_type:
                        continue
                    next_frontier.add(neighbor)
                    visited.add(neighbor)
        frontier = next_frontier

    # Build subgraph
    subgraph = G.subgraph(visited)
    nodes = [
        {
            "name": n,
            "type": subgraph.nodes[n].get("entity_type"),
            "attributes": subgraph.nodes[n].get("attributes", {}),
        }
        for n in subgraph.nodes
    ]
    edges = [
        {
            "source": u,
            "target": v,
            "predicate": d.get("predicate"),
            "confidence": d.get("confidence"),
        }
        for u, v, d in subgraph.edges(data=True)
    ]
    return {"nodes": nodes, "edges": edges}


def find_path(conn, from_name: str, to_name: str, max_depth: int = 5) -> list[dict] | None:
    """Find shortest path between two entities."""
    G = _build_graph(conn)
    if from_name not in G or to_name not in G:
        return None

    # Try undirected path
    UG = G.to_undirected()
    try:
        path_nodes = nx.shortest_path(UG, from_name, to_name)
    except nx.NetworkXNoPath:
        return None

    if len(path_nodes) - 1 > max_depth:
        return None

    # Build edge list along path
    edges = []
    for i in range(len(path_nodes) - 1):
        u, v = path_nodes[i], path_nodes[i + 1]
        # Check directed edge in either direction
        if G.has_edge(u, v):
            d = G.edges[u, v]
            edges.append({"source": u, "target": v, "predicate": d.get("predicate")})
        elif G.has_edge(v, u):
            d = G.edges[v, u]
            edges.append({"source": v, "target": u, "predicate": d.get("predicate")})
    return edges


def get_current_schema(conn) -> dict | None:
    """Get the current induced schema."""
    import yaml

    row = conn.execute("SELECT * FROM current_schema").fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "llm_model": row["llm_model"],
        "entity_type_count": row["entity_type_count"],
        "relation_type_count": row["relation_type_count"],
        "schema": yaml.safe_load(row["schema_yaml"]),
        "notes": row["notes"],
    }
