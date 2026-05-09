"""Schema induction: generate typed schema from the resolved knowledge graph."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import litellm
import yaml

from kgmd.llm import _strip_code_fences


def _load_prompt_template(corpus_dir: Path | None = None) -> str:
    """Load the induction prompt template."""
    if corpus_dir:
        user_prompt = corpus_dir / ".kgmd" / "prompts" / "induce.txt"
        if user_prompt.exists():
            return user_prompt.read_text()
    bundled = Path(__file__).parent / "prompts" / "induce.txt"
    return bundled.read_text()


def _gather_entity_stats(conn) -> str:
    """Aggregate entity type statistics for the LLM."""
    types = conn.execute(
        "SELECT entity_type, COUNT(*) as cnt FROM entities GROUP BY entity_type ORDER BY cnt DESC"
    ).fetchall()

    lines = []
    for t in types:
        lines.append(f"\n### {t['entity_type']} ({t['cnt']} entities)")

        # Top 20 attribute keys
        entities = conn.execute(
            "SELECT attributes FROM entities WHERE entity_type = ? LIMIT 100",
            (t["entity_type"],),
        ).fetchall()

        attr_counts: dict[str, int] = {}
        for e in entities:
            attrs = json.loads(e["attributes"])
            for k in attrs:
                attr_counts[k] = attr_counts.get(k, 0) + 1

        if attr_counts:
            sorted_attrs = sorted(attr_counts.items(), key=lambda x: -x[1])[:20]
            for ak, ac in sorted_attrs:
                freq = ac / t["cnt"]
                lines.append(f"  - {ak}: frequency={freq:.2f}")

    return "\n".join(lines) if lines else "(no entities yet)"


def _gather_relation_stats(conn) -> str:
    """Aggregate relation predicate statistics."""
    preds = conn.execute(
        "SELECT predicate, COUNT(*) as cnt FROM relations GROUP BY predicate ORDER BY cnt DESC"
    ).fetchall()

    lines = []
    for p in preds:
        lines.append(f"\n### {p['predicate']} ({p['cnt']} relations)")

        # Subject/object type distribution
        pairs = conn.execute(
            """SELECT se.entity_type as stype, oe.entity_type as otype, COUNT(*) as cnt
               FROM relations r
               JOIN entities se ON se.id = r.subject_id
               JOIN entities oe ON oe.id = r.object_id
               WHERE r.predicate = ?
               GROUP BY stype, otype ORDER BY cnt DESC LIMIT 10""",
            (p["predicate"],),
        ).fetchall()

        for pair in pairs:
            lines.append(f"  - {pair['stype']} → {pair['otype']}: {pair['cnt']}")

    return "\n".join(lines) if lines else "(no relations yet)"


def run_induction(conn, config: dict, corpus_dir: Path | None = None) -> dict:
    """Run schema induction using LLM."""
    llm_cfg = config.get("llm", {})
    model = llm_cfg.get("model", "openrouter/anthropic/claude-sonnet-4-5")
    ind_cfg = config.get("induction", {})
    hierarchy_depth = ind_cfg.get("hierarchy_depth", 3)

    # Check if there are entities to induce from
    entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    if entity_count == 0:
        return {"entity_type_count": 0, "relation_type_count": 0}

    entity_stats = _gather_entity_stats(conn)
    relation_stats = _gather_relation_stats(conn)

    now = datetime.now(timezone.utc).isoformat()
    prompt_template = _load_prompt_template(corpus_dir)

    system_prompt = prompt_template.format(
        entity_stats=entity_stats,
        relation_stats=relation_stats,
        hierarchy_depth=hierarchy_depth,
        timestamp=now,
    )

    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Generate the schema now."},
        ],
        temperature=0.0,
        max_tokens=4096,
    )

    content = response.choices[0].message.content
    content = _strip_code_fences(content)

    # Parse the YAML
    schema = yaml.safe_load(content)
    if not isinstance(schema, dict):
        schema = {}

    # Count types
    entity_types = schema.get("entity_types", {})
    relation_types = schema.get("relation_types", {})
    et_count = len(entity_types)
    rt_count = len(relation_types)

    # Validate coverage
    db_types = set(
        r["entity_type"]
        for r in conn.execute("SELECT DISTINCT entity_type FROM entities").fetchall()
    )
    db_preds = set(
        r["predicate"] for r in conn.execute("SELECT DISTINCT predicate FROM relations").fetchall()
    )

    schema_types = set(entity_types.keys())
    # Also collect children
    for et in entity_types.values():
        if isinstance(et, dict):
            for child in et.get("children", []):
                schema_types.add(child)

    schema_preds = set(relation_types.keys())

    missing_types = db_types - schema_types
    missing_preds = db_preds - schema_preds

    if missing_types or missing_preds:
        # Re-prompt once with missing types
        correction = (
            f"Missing entity types: {missing_types}. "
            f"Missing predicates: {missing_preds}. "
            "Please include them."
        )
        response2 = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the schema now."},
                {"role": "assistant", "content": content},
                {"role": "user", "content": correction},
            ],
            temperature=0.0,
            max_tokens=4096,
        )
        content2 = _strip_code_fences(response2.choices[0].message.content)
        try:
            schema = yaml.safe_load(content2)
            entity_types = schema.get("entity_types", {})
            relation_types = schema.get("relation_types", {})
            et_count = len(entity_types)
            rt_count = len(relation_types)
        except Exception:
            pass  # Keep original schema

    schema_yaml = yaml.dump(schema, default_flow_style=False, sort_keys=False)

    # Persist
    conn.execute(
        """INSERT INTO schema_versions
           (created_at, llm_model, schema_yaml, entity_type_count, relation_type_count)
           VALUES (?, ?, ?, ?, ?)""",
        (now, model, schema_yaml, et_count, rt_count),
    )
    conn.commit()

    return {"entity_type_count": et_count, "relation_type_count": rt_count}
