"""Extraction stage: LLM-based entity and relation extraction from chunks."""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from rich.progress import Progress

from kgmd.llm import call_structured
from kgmd.schema import ExtractionResult

logger = logging.getLogger("kgmd.extract")


def _load_prompt_template(corpus_dir: Path) -> str:
    """Load the extraction prompt, preferring user override."""
    user_prompt = corpus_dir / ".kgmd" / "prompts" / "extract.txt"
    if user_prompt.exists():
        return user_prompt.read_text()
    # Fall back to bundled default
    bundled = Path(__file__).parent / "prompts" / "extract.txt"
    return bundled.read_text()


def _get_type_vocabulary(conn, top_n: int = 50) -> str:
    """Get the top N most-common entity types."""
    rows = conn.execute(
        "SELECT entity_type, COUNT(*) as cnt FROM entities"
        " GROUP BY entity_type ORDER BY cnt DESC LIMIT ?",
        (top_n,),
    ).fetchall()
    if not rows:
        return "(none yet — use your best judgment)"
    return ", ".join(r["entity_type"] for r in rows)


def _get_predicate_vocabulary(conn, top_n: int = 50) -> str:
    """Get the top N most-common relation predicates."""
    rows = conn.execute(
        "SELECT predicate, COUNT(*) as cnt FROM relations"
        " GROUP BY predicate ORDER BY cnt DESC LIMIT ?",
        (top_n,),
    ).fetchall()
    if not rows:
        return "(none yet — use your best judgment)"
    return ", ".join(r["predicate"] for r in rows)


def _extract_chunk(
    model: str,
    system_prompt: str,
    chunk_content: str,
    max_retries: int,
    temperature: float,
    max_tokens: int,
    timeout: int,
    log_path: Path,
) -> ExtractionResult | None:
    """Extract entities/relations from a single chunk. Thread-safe (no DB access)."""
    try:
        return call_structured(
            model=model,
            system=system_prompt,
            user=chunk_content,
            response_model=ExtractionResult,
            max_retries=max_retries,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            log_path=log_path,
        )
    except Exception as e:
        logger.warning(f"Extraction failed: {e}")
        return None


def run_extraction(conn, corpus_dir: Path, config: dict, force: bool = False) -> dict:
    """Run extraction on all documents that need it."""
    llm_cfg = config.get("llm", {})
    model = llm_cfg.get("model", "openrouter/anthropic/claude-sonnet-4-5")
    temperature = llm_cfg.get("temperature", 0.0)
    max_tokens = llm_cfg.get("max_tokens", 4096)
    timeout = llm_cfg.get("timeout_seconds", 120)
    concurrency = llm_cfg.get("concurrency", 4)

    ext_cfg = config.get("extraction", {})
    max_retries = ext_cfg.get("retry_on_parse_failure", 2)

    log_path = corpus_dir / ".kgmd" / "logs" / "build.log"
    prompt_template = _load_prompt_template(corpus_dir)

    now = datetime.now(timezone.utc).isoformat()

    # Create extraction run
    cur = conn.execute(
        "INSERT INTO extraction_runs (started_at, model, status) VALUES (?, ?, 'running')",
        (now, model),
    )
    run_id = cur.lastrowid
    conn.commit()

    # Get documents to extract
    if force:
        docs = conn.execute("SELECT id, path, content_hash FROM documents").fetchall()
    else:
        docs = conn.execute(
            "SELECT id, path, content_hash FROM documents"
            " WHERE last_extracted_hash IS NULL"
            " OR last_extracted_hash != content_hash"
        ).fetchall()

    stats = {"documents_processed": 0, "entities_created": 0, "relations_created": 0}

    entity_types = _get_type_vocabulary(conn)
    predicates = _get_predicate_vocabulary(conn)

    # Collect all chunks across all docs for parallel processing
    all_chunks = []
    for doc in docs:
        doc_id = doc["id"]
        if force:
            _clean_doc_extractions(conn, doc_id)
        chunks = conn.execute(
            "SELECT id, content FROM chunks WHERE document_id = ? ORDER BY chunk_index",
            (doc_id,),
        ).fetchall()
        for chunk in chunks:
            all_chunks.append((doc_id, chunk["id"], chunk["content"]))

    # Build initial system prompt
    system_prompt = prompt_template.format(
        entity_types=entity_types,
        relation_predicates=predicates,
    )

    # Track which docs had at least one successful chunk
    doc_success = set()
    db_lock = threading.Lock()
    vocab_refresh_counter = 0

    with Progress() as progress:
        task = progress.add_task("Extracting", total=len(all_chunks))

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            # Submit all chunk extractions
            future_to_chunk = {}
            for doc_id, chunk_id, chunk_content in all_chunks:
                future = executor.submit(
                    _extract_chunk,
                    model,
                    system_prompt,
                    chunk_content,
                    max_retries,
                    temperature,
                    max_tokens,
                    timeout,
                    log_path,
                )
                future_to_chunk[future] = (doc_id, chunk_id)

            for future in as_completed(future_to_chunk):
                doc_id, chunk_id = future_to_chunk[future]
                result = future.result()

                if result is None:
                    progress.advance(task)
                    continue

                doc_success.add(doc_id)

                # DB writes are serialized
                with db_lock:
                    for ent in result.entities:
                        entity_id = _upsert_entity(conn, ent, now)
                        conn.execute(
                            "INSERT INTO entity_mentions"
                            " (entity_id, surface_form, chunk_id,"
                            " char_start, char_end,"
                            " extraction_run_id, confidence)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                entity_id,
                                ent.surface_form,
                                chunk_id,
                                ent.char_start,
                                ent.char_end,
                                run_id,
                                ent.confidence,
                            ),
                        )
                        stats["entities_created"] += 1

                    for rel in result.relations:
                        _insert_relation(conn, rel, chunk_id, run_id, now)
                        stats["relations_created"] += 1

                    # Refresh vocabulary every 10 chunks
                    vocab_refresh_counter += 1
                    if vocab_refresh_counter % 10 == 0:
                        entity_types = _get_type_vocabulary(conn)
                        predicates = _get_predicate_vocabulary(conn)
                        system_prompt = prompt_template.format(
                            entity_types=entity_types,
                            relation_predicates=predicates,
                        )

                progress.advance(task)

    # Mark successful docs as extracted
    for doc in docs:
        if doc["id"] in doc_success:
            conn.execute(
                "UPDATE documents SET last_extracted_hash = content_hash WHERE id = ?",
                (doc["id"],),
            )
        stats["documents_processed"] += 1

    # Finalize run
    conn.execute(
        "UPDATE extraction_runs SET finished_at = ?,"
        " status = 'completed', documents_processed = ?"
        " WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), stats["documents_processed"], run_id),
    )
    conn.commit()
    return stats


def _upsert_entity(conn, ent, now: str) -> int:
    """Insert or update an entity, returning its id."""
    # Normalize type to lowercase to prevent "Date" vs "date" duplicates
    entity_type = ent.entity_type.lower().replace(" ", "_")
    row = conn.execute(
        "SELECT id, attributes FROM entities WHERE canonical_name = ? AND entity_type = ?",
        (ent.canonical_name, entity_type),
    ).fetchone()

    if row:
        # Merge attributes
        existing = json.loads(row["attributes"])
        existing.update(ent.attributes)
        conn.execute(
            "UPDATE entities SET attributes = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing), now, row["id"]),
        )
        return row["id"]
    else:
        conn.execute(
            "INSERT OR IGNORE INTO entities"
            " (canonical_name, entity_type, attributes,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (ent.canonical_name, entity_type, json.dumps(ent.attributes), now, now),
        )
        # Fetch the id whether we just inserted or it already existed
        row = conn.execute(
            "SELECT id FROM entities WHERE canonical_name = ? AND entity_type = ?",
            (ent.canonical_name, entity_type),
        ).fetchone()
        return row["id"]


def _insert_relation(conn, rel, chunk_id: int, run_id: int, now: str) -> None:
    """Insert a relation, resolving subject/object by canonical name."""
    sub = conn.execute(
        "SELECT id FROM entities WHERE canonical_name = ?", (rel.subject,)
    ).fetchone()
    obj = conn.execute("SELECT id FROM entities WHERE canonical_name = ?", (rel.object,)).fetchone()

    if not sub or not obj:
        return

    conn.execute(
        "INSERT OR IGNORE INTO relations"
        " (subject_id, predicate, object_id,"
        " evidence_chunk_id, extraction_run_id,"
        " confidence, attributes, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sub["id"],
            rel.predicate,
            obj["id"],
            chunk_id,
            run_id,
            rel.confidence,
            json.dumps(rel.attributes),
            now,
        ),
    )


def _clean_doc_extractions(conn, doc_id: int) -> None:
    """Remove old extraction data for a document when re-extracting."""
    chunk_ids = [
        r["id"]
        for r in conn.execute("SELECT id FROM chunks WHERE document_id = ?", (doc_id,)).fetchall()
    ]

    if not chunk_ids:
        return

    placeholders = ",".join("?" * len(chunk_ids))
    conn.execute(f"DELETE FROM entity_mentions WHERE chunk_id IN ({placeholders})", chunk_ids)
    conn.execute(f"DELETE FROM relations WHERE evidence_chunk_id IN ({placeholders})", chunk_ids)
