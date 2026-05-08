"""Tests for export formats."""

import json
import xml.etree.ElementTree as ET

from kgmd.export import export_cypher, export_graphml, export_jsonld


def test_export_jsonld(seeded_db):
    """Test JSON-LD export."""
    result = export_jsonld(seeded_db)
    data = json.loads(result)

    assert "@context" in data
    assert "@graph" in data
    assert len(data["@graph"]) > 0

    # Check some entity is present
    names = [n.get("name") for n in data["@graph"] if "name" in n]
    assert "Brian Anderson" in names


def test_export_jsonld_roundtrip(seeded_db):
    """Test that JSON-LD is valid JSON."""
    result = export_jsonld(seeded_db)
    # Should parse without error
    data = json.loads(result)
    # And re-serialize
    json.dumps(data)


def test_export_cypher(seeded_db):
    """Test Cypher export."""
    result = export_cypher(seeded_db)
    lines = result.strip().split("\n")

    assert len(lines) > 0
    # Should have CREATE statements for entities
    create_nodes = [line for line in lines if line.startswith("CREATE (e")]
    assert len(create_nodes) >= 5

    # Should have CREATE statements for relations
    create_rels = [line for line in lines if ")-[:" in line]
    assert len(create_rels) >= 4


def test_export_graphml(seeded_db):
    """Test GraphML export."""
    result = export_graphml(seeded_db)

    # Should be valid XML
    root = ET.fromstring(result)
    assert root is not None

    # Find nodes and edges
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    graph = root.find(".//g:graph", ns)
    assert graph is not None

    nodes = graph.findall("g:node", ns)
    edges = graph.findall("g:edge", ns)
    assert len(nodes) >= 5
    assert len(edges) >= 4


def test_export_graphml_roundtrip(seeded_db):
    """Test that GraphML can be parsed back."""
    result = export_graphml(seeded_db)
    # Parse with NetworkX
    from io import BytesIO

    import networkx as nx

    G = nx.read_graphml(BytesIO(result.encode("utf-8")))
    assert len(G.nodes) >= 5
    assert len(G.edges) >= 4
