"""Entity resolution: embedding-based clustering + LLM verification."""

from __future__ import annotations

import json
import struct
from datetime import datetime, timezone
from pathlib import Path

from kgmd.llm import call_structured
from kgmd.schema import ResolutionResult


def _load_prompt_template(corpus_dir: Path | None = None) -> str:
    """Load the resolution prompt template."""
    if corpus_dir:
        user_prompt = corpus_dir / ".kgmd" / "prompts" / "resolve.txt"
        if user_prompt.exists():
            return user_prompt.read_text()
    bundled = Path(__file__).parent / "prompts" / "resolve.txt"
    return bundled.read_text()


def run_resolution(conn, config: dict, corpus_dir: Path | None = None) -> dict:
    """Run entity resolution: cluster by embedding similarity, then LLM-verify."""
    res_cfg = config.get("resolution", {})
    threshold = res_cfg.get("similarity_threshold", 0.85)
    verify = res_cfg.get("llm_verify_clusters", True)
    max_cluster_size = res_cfg.get("max_cluster_size", 10)

    llm_cfg = config.get("llm", {})
    model = llm_cfg.get("model", "openrouter/anthropic/claude-sonnet-4-5")

    emb_cfg = config.get("embedding", {})
    emb_model = emb_cfg.get("model", "BAAI/bge-small-en-v1.5")

    now = datetime.now(timezone.utc).isoformat()

    # Create resolution run
    cur = conn.execute(
        "INSERT INTO resolution_runs (started_at, embedding_model, llm_model, similarity_threshold, status) VALUES (?, ?, ?, ?, 'running')",
        (now, emb_model, model, threshold),
    )
    run_id = cur.lastrowid
    conn.commit()

    # Load all entity mentions with embeddings
    mentions = conn.execute(
        """SELECT em.id, em.entity_id, em.surface_form, e.entity_type, e.canonical_name,
                  v.embedding
           FROM entity_mentions em
           JOIN entities e ON e.id = em.entity_id
           JOIN vec_entity_mentions v ON v.mention_id = em.id"""
    ).fetchall()

    if len(mentions) < 2:
        _finalize_run(conn, run_id, 0)
        return {"merges": 0}

    # Group by entity_type for clustering
    by_type: dict[str, list] = {}
    for m in mentions:
        t = m["entity_type"]
        by_type.setdefault(t, []).append(m)

    total_merges = 0

    for entity_type, type_mentions in by_type.items():
        if len(type_mentions) < 2:
            continue

        # Build clusters using union-find on cosine similarity
        clusters = _cluster_by_similarity(type_mentions, threshold, max_cluster_size)

        # Filter singletons
        clusters = [c for c in clusters if len(c) > 1]

        if not clusters:
            continue

        for cluster in clusters:
            entity_ids = list(set(m["entity_id"] for m in cluster))
            if len(entity_ids) < 2:
                continue  # All mentions already belong to same entity

            surface_forms = [m["surface_form"] for m in cluster]

            if verify:
                # LLM verification
                verified_partitions = _verify_cluster(conn, cluster, entity_type, model, corpus_dir)
            else:
                verified_partitions = [
                    {"canonical_name": surface_forms[0], "members": surface_forms}
                ]

            # Merge verified partitions
            for partition in verified_partitions:
                merge_ids = set()
                for m in cluster:
                    if m["surface_form"] in partition["members"]:
                        merge_ids.add(m["entity_id"])

                if len(merge_ids) < 2:
                    continue

                merge_ids = sorted(merge_ids)
                survivor_id = merge_ids[0]
                canonical = partition.get("canonical_name") or _most_frequent_surface(
                    conn, merge_ids
                )

                _merge_entities(conn, survivor_id, merge_ids[1:], canonical)
                total_merges += len(merge_ids) - 1

    _finalize_run(conn, run_id, total_merges)
    return {"merges": total_merges}


def _cluster_by_similarity(mentions: list, threshold: float, max_size: int) -> list[list]:
    """Build connected components using union-find on cosine similarity."""
    n = len(mentions)
    # Parse embeddings
    vecs = []
    dim = None
    for m in mentions:
        raw = m["embedding"]
        if dim is None:
            dim = len(raw) // 4
        vec = struct.unpack(f"{dim}f", raw)
        vecs.append(vec)

    # Union-Find
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # Compare all pairs
    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine_similarity(vecs[i], vecs[j])
            if sim >= threshold:
                union(i, j)

    # Group by root
    groups: dict[int, list] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(mentions[i])

    # Split oversized clusters
    result = []
    for members in groups.values():
        if len(members) <= max_size:
            result.append(members)
        else:
            # Sub-cluster at higher threshold
            sub = _cluster_by_similarity(members, threshold + 0.05, max_size)
            result.extend(sub)

    return result


def _cosine_similarity(a: tuple, b: tuple) -> float:
    """Compute cosine similarity between two vectors."""
    import math

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _verify_cluster(
    conn, cluster: list, entity_type: str, model: str, corpus_dir: Path | None
) -> list[dict]:
    """Use LLM to verify whether cluster members are the same entity."""
    prompt_template = _load_prompt_template(corpus_dir)

    # Build cluster details
    details_lines = []
    for m in cluster:
        # Get a snippet of evidence
        chunk = conn.execute(
            "SELECT content FROM chunks c JOIN entity_mentions em ON em.chunk_id = c.id WHERE em.id = ?",
            (m["id"],),
        ).fetchone()
        snippet = chunk["content"][:150] if chunk else ""
        details_lines.append(
            f'- "{m["surface_form"]}" (entity: {m["canonical_name"]}): ...{snippet}...'
        )

    cluster_details = "\n".join(details_lines)

    system_prompt = prompt_template.format(
        entity_type=entity_type,
        cluster_details=cluster_details,
    )

    try:
        result = call_structured(
            model=model,
            system=system_prompt,
            user="Evaluate this cluster.",
            response_model=ResolutionResult,
        )
        return [p.model_dump() for p in result.partitions]
    except Exception:
        # On failure, assume they're all the same (conservative)
        all_forms = [m["surface_form"] for m in cluster]
        return [{"canonical_name": all_forms[0], "members": all_forms}]


def _most_frequent_surface(conn, entity_ids: list[int]) -> str:
    """Return the most frequently occurring surface form among entity ids."""
    placeholders = ",".join("?" * len(entity_ids))
    row = conn.execute(
        f"""SELECT surface_form, COUNT(*) as cnt FROM entity_mentions
            WHERE entity_id IN ({placeholders})
            GROUP BY surface_form ORDER BY cnt DESC LIMIT 1""",
        entity_ids,
    ).fetchone()
    return row["surface_form"] if row else ""


def _merge_entities(conn, survivor_id: int, drop_ids: list[int], canonical_name: str) -> None:
    """Merge dropped entities into the survivor."""
    # Merge attributes before deleting drops
    survivor_attrs = json.loads(
        conn.execute("SELECT attributes FROM entities WHERE id = ?", (survivor_id,)).fetchone()[
            "attributes"
        ]
    )
    for did in drop_ids:
        row = conn.execute("SELECT attributes FROM entities WHERE id = ?", (did,)).fetchone()
        if row:
            other = json.loads(row["attributes"])
            survivor_attrs.update(other)

    conn.execute(
        "UPDATE entities SET attributes = ? WHERE id = ?",
        (json.dumps(survivor_attrs), survivor_id),
    )

    # Re-point mentions from dropped entities to survivor
    for did in drop_ids:
        conn.execute(
            "UPDATE entity_mentions SET entity_id = ? WHERE entity_id = ?",
            (survivor_id, did),
        )

    # Re-point relations from dropped entities to survivor
    for did in drop_ids:
        conn.execute(
            "UPDATE relations SET subject_id = ? WHERE subject_id = ?",
            (survivor_id, did),
        )
        conn.execute(
            "UPDATE relations SET object_id = ? WHERE object_id = ?",
            (survivor_id, did),
        )

    # Deduplicate relations after rewrite
    conn.execute("""
        DELETE FROM relations WHERE id NOT IN (
            SELECT MIN(id) FROM relations
            GROUP BY subject_id, predicate, object_id, evidence_chunk_id
        )
    """)

    # Delete dropped entities BEFORE renaming survivor to avoid UNIQUE conflict
    for did in drop_ids:
        conn.execute("DELETE FROM entities WHERE id = ?", (did,))

    # Now safe to update canonical name
    conn.execute(
        "UPDATE entities SET canonical_name = ?, updated_at = ? WHERE id = ?",
        (canonical_name, datetime.now(timezone.utc).isoformat(), survivor_id),
    )

    conn.commit()


def _finalize_run(conn, run_id: int, merges: int) -> None:
    conn.execute(
        "UPDATE resolution_runs SET finished_at = ?, merges = ?, status = 'completed' WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), merges, run_id),
    )
    conn.commit()
