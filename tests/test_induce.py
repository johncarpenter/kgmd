"""Tests for schema induction with mocked LLM."""

from unittest.mock import MagicMock, patch

from kgmd.induce import run_induction


def _mock_litellm_response(content: str):
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = content
    return mock


def test_induction_no_entities(initialized_corpus):
    """Test induction with no entities returns empty."""
    from kgmd.config import load_config
    from kgmd.db import get_connection

    db_path = initialized_corpus / ".kgmd" / "graph.db"
    conn = get_connection(db_path)
    config = load_config(initialized_corpus)

    stats = run_induction(conn, config)
    assert stats["entity_type_count"] == 0
    assert stats["relation_type_count"] == 0
    conn.close()


def test_induction_with_seeded_data(seeded_db):
    """Test schema induction with seeded data and mocked LLM."""

    config = {
        "llm": {"model": "test-model"},
        "induction": {"hierarchy_depth": 3},
    }

    schema_yaml = """\
version: 1
generated_at: '2026-05-07T00:00:00Z'
entity_types:
  Person:
    description: An individual human.
    attributes:
      role: {type: string, frequency: 0.5}
    parent: null
    children: []
  Organization:
    description: A company or institution.
    attributes:
      industry: {type: string, frequency: 0.25}
    parent: null
    children: []
  Project:
    description: A named initiative.
    attributes: {}
    parent: null
    children: []
relation_types:
  works_at:
    description: Employment relationship.
    subject_types: [Person]
    object_types: [Organization]
    frequency: 2
  leads:
    description: Leadership of a project.
    subject_types: [Person]
    object_types: [Project]
    frequency: 1
  runs:
    description: Organization runs a project.
    subject_types: [Organization]
    object_types: [Project]
    frequency: 1
"""

    mock_response = _mock_litellm_response(schema_yaml)

    with patch("kgmd.induce.litellm.completion", return_value=mock_response):
        stats = run_induction(seeded_db, config)

    assert stats["entity_type_count"] == 3
    assert stats["relation_type_count"] == 3

    # Verify persisted
    row = seeded_db.execute("SELECT * FROM schema_versions ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert "Person" in row["schema_yaml"]
