"""Tests for extraction with mocked LLM responses."""

import json
from unittest.mock import MagicMock, patch

from kgmd.extract import run_extraction


def _mock_litellm_response(content: str):
    """Create a mock litellm response."""
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = content
    return mock


def test_extraction_with_mocked_llm(initialized_corpus, db_conn):
    """Test extraction end-to-end with a mocked LLM."""
    from kgmd.config import load_config
    from kgmd.ingest import ingest_documents

    config = load_config(initialized_corpus)

    # Ingest first
    ingest_documents(db_conn, initialized_corpus, config)

    # Mock LLM response
    extraction_json = json.dumps(
        {
            "entities": [
                {
                    "surface_form": "Brian Anderson",
                    "canonical_name": "Brian Anderson",
                    "entity_type": "Person",
                    "attributes": {"role": "CFO"},
                    "confidence": 0.95,
                },
                {
                    "surface_form": "CFO Centre Canada",
                    "canonical_name": "CFO Centre Canada",
                    "entity_type": "Organization",
                    "attributes": {},
                    "confidence": 0.9,
                },
            ],
            "relations": [
                {
                    "subject": "Brian Anderson",
                    "predicate": "works_at",
                    "object": "CFO Centre Canada",
                    "attributes": {},
                    "confidence": 0.9,
                }
            ],
        }
    )

    mock_response = _mock_litellm_response(extraction_json)

    with patch("kgmd.llm.litellm.completion", return_value=mock_response):
        stats = run_extraction(db_conn, initialized_corpus, config)

    assert stats["documents_processed"] > 0
    assert stats["entities_created"] > 0
    assert stats["relations_created"] > 0

    # Verify entities were inserted
    entities = db_conn.execute("SELECT * FROM entities").fetchall()
    assert len(entities) >= 2

    names = [e["canonical_name"] for e in entities]
    assert "Brian Anderson" in names
    assert "CFO Centre Canada" in names

    # Verify relations
    rels = db_conn.execute("SELECT * FROM relations").fetchall()
    assert len(rels) >= 1


def test_extraction_idempotent(initialized_corpus, db_conn):
    """Test that re-extraction on unchanged docs is skipped."""
    from kgmd.config import load_config
    from kgmd.ingest import ingest_documents

    config = load_config(initialized_corpus)
    ingest_documents(db_conn, initialized_corpus, config)

    extraction_json = json.dumps({"entities": [], "relations": []})
    mock_response = _mock_litellm_response(extraction_json)

    with patch("kgmd.llm.litellm.completion", return_value=mock_response):
        run_extraction(db_conn, initialized_corpus, config)
        stats2 = run_extraction(db_conn, initialized_corpus, config)

    # Second run should process 0 docs (all have last_extracted_hash set)
    assert stats2["documents_processed"] == 0


def test_extraction_json_with_code_fences(initialized_corpus, db_conn):
    """Test that LLM response wrapped in code fences is handled."""
    from kgmd.config import load_config
    from kgmd.ingest import ingest_documents

    config = load_config(initialized_corpus)
    ingest_documents(db_conn, initialized_corpus, config)

    extraction_json = '```json\n{"entities": [], "relations": []}\n```'
    mock_response = _mock_litellm_response(extraction_json)

    with patch("kgmd.llm.litellm.completion", return_value=mock_response):
        stats = run_extraction(db_conn, initialized_corpus, config)

    assert stats["documents_processed"] > 0
