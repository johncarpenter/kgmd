"""Export the knowledge graph: JSON-LD, Cypher, GraphML."""

from __future__ import annotations

import json

import networkx as nx


def _load_graph(conn) -> tuple[list[dict], list[dict]]:
    """Load all entities and relations from the database."""
    entities = conn.execute(
        "SELECT id, canonical_name, entity_type, attributes FROM entities"
    ).fetchall()

    relations = conn.execute(
        """SELECT r.id, r.predicate, r.confidence, r.attributes,
                  s.canonical_name as subject_name, s.entity_type as subject_type,
                  o.canonical_name as object_name, o.entity_type as object_type
           FROM relations r
           JOIN entities s ON s.id = r.subject_id
           JOIN entities o ON o.id = r.object_id"""
    ).fetchall()

    entity_list = [
        {
            "id": e["id"],
            "name": e["canonical_name"],
            "type": e["entity_type"],
            "attributes": json.loads(e["attributes"]),
        }
        for e in entities
    ]

    relation_list = [
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
        for r in relations
    ]

    return entity_list, relation_list


# Schema.org type mappings for common entity types
_SCHEMA_ORG_TYPES = {
    "Person": "schema:Person",
    "Organization": "schema:Organization",
    "Location": "schema:Place",
    "Place": "schema:Place",
    "Event": "schema:Event",
    "Project": "schema:Project",
    "Technology": "schema:SoftwareApplication",
    "Product": "schema:Product",
}


def export_jsonld(conn) -> str:
    """Export as JSON-LD."""
    entities, relations = _load_graph(conn)

    context = {
        "schema": "https://schema.org/",
        "kg": "https://kgmd.local/",
        "name": "schema:name",
        "type": "@type",
    }

    nodes = []
    for e in entities:
        node = {
            "@id": f"kg:entity/{e['id']}",
            "name": e["name"],
            "type": _SCHEMA_ORG_TYPES.get(e["type"], f"kg:{e['type']}"),
            "kg:entityType": e["type"],
        }
        for k, v in e["attributes"].items():
            node[f"kg:{k}"] = v
        nodes.append(node)

    edges = []
    for r in relations:
        edge = {
            "@type": "kg:Relation",
            "kg:subject": f"kg:entity/{_entity_id_by_name(entities, r['subject'])}",
            "kg:predicate": r["predicate"],
            "kg:object": f"kg:entity/{_entity_id_by_name(entities, r['object'])}",
        }
        if r["confidence"] is not None:
            edge["kg:confidence"] = r["confidence"]
        for k, v in r["attributes"].items():
            edge[f"kg:{k}"] = v
        edges.append(edge)

    doc = {
        "@context": context,
        "@graph": nodes + edges,
    }

    return json.dumps(doc, indent=2)


def _entity_id_by_name(entities: list[dict], name: str) -> int:
    for e in entities:
        if e["name"] == name:
            return e["id"]
    return 0


def export_cypher(conn) -> str:
    """Export as Cypher CREATE statements."""
    entities, relations = _load_graph(conn)

    lines = []

    for e in entities:
        label = e["type"].replace(" ", "_")
        props = {"name": e["name"]}
        props.update(e["attributes"])
        props_str = _cypher_props(props)
        lines.append(f"CREATE (e{e['id']}:{label} {props_str});")

    for r in relations:
        sub_id = _entity_id_by_name(entities, r["subject"])
        obj_id = _entity_id_by_name(entities, r["object"])
        rel_type = r["predicate"].upper().replace(" ", "_")
        props = dict(r["attributes"])
        if r["confidence"] is not None:
            props["confidence"] = r["confidence"]
        if props:
            props_str = f" {_cypher_props(props)}"
        else:
            props_str = ""
        lines.append(f"CREATE (e{sub_id})-[:{rel_type}{props_str}]->(e{obj_id});")

    return "\n".join(lines)


def _cypher_props(props: dict) -> str:
    """Format a dict as Cypher property string."""
    parts = []
    for k, v in props.items():
        key = k.replace(" ", "_").replace("-", "_")
        if isinstance(v, str):
            escaped = v.replace("\\", "\\\\").replace("'", "\\'")
            parts.append(f"{key}: '{escaped}'")
        elif isinstance(v, (int, float)):
            parts.append(f"{key}: {v}")
        elif isinstance(v, bool):
            parts.append(f"{key}: {'true' if v else 'false'}")
        else:
            escaped = str(v).replace("\\", "\\\\").replace("'", "\\'")
            parts.append(f"{key}: '{escaped}'")
    return "{" + ", ".join(parts) + "}"


def export_graphml(conn) -> str:
    """Export as GraphML using NetworkX."""
    entities, relations = _load_graph(conn)

    G = nx.DiGraph()

    for e in entities:
        G.add_node(
            str(e["id"]),
            label=e["name"],
            entity_type=e["type"],
            **{k: str(v) for k, v in e["attributes"].items()},
        )

    for r in relations:
        sub_id = str(_entity_id_by_name(entities, r["subject"]))
        obj_id = str(_entity_id_by_name(entities, r["object"]))
        G.add_edge(
            sub_id,
            obj_id,
            label=r["predicate"],
            predicate=r["predicate"],
            confidence=str(r["confidence"]) if r["confidence"] is not None else "",
        )

    from io import BytesIO

    buf = BytesIO()
    nx.write_graphml(G, buf)
    return buf.getvalue().decode("utf-8")
