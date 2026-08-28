"""Markdown reading, chunking, and hashing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from kgmd.ignore import is_ignored, load_ignore_rules


@dataclass
class Chunk:
    content: str
    char_start: int
    char_end: int
    chunk_index: int
    token_count: int


def hash_content(text: str) -> str:
    """Compute sha256 hex digest of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_markdown(
    text: str,
    max_chars: int = 4000,
    overlap_chars: int = 200,
    split_on: str = "paragraph",
) -> list[Chunk]:
    """Split markdown text into chunks with character offsets.

    split_on:
      "paragraph": split on double newlines, merge adjacent paragraphs until max_chars.
      "heading":   split on markdown headings (# ## ###), merge similarly.
      "fixed":     fixed-size windows with overlap.
    """
    if not text.strip():
        return []

    if split_on == "fixed":
        return _chunk_fixed(text, max_chars, overlap_chars)
    elif split_on == "heading":
        return _chunk_by_pattern(text, max_chars, _HEADING_PATTERN)
    else:  # paragraph
        return _chunk_by_pattern(text, max_chars, _PARAGRAPH_PATTERN)


_PARAGRAPH_PATTERN = re.compile(r"\n\s*\n")
_HEADING_PATTERN = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)


def _chunk_by_pattern(text: str, max_chars: int, pattern: re.Pattern) -> list[Chunk]:
    """Split text by a regex pattern, then merge segments up to max_chars."""
    segments = pattern.split(text)
    # Track character offsets for each segment
    offsets: list[tuple[int, int]] = []
    pos = 0
    for seg in segments:
        start = text.find(seg, pos)
        offsets.append((start, start + len(seg)))
        pos = start + len(seg)

    chunks: list[Chunk] = []
    current_segs: list[int] = []  # indices into segments
    current_len = 0

    for i, seg in enumerate(segments):
        seg_len = len(seg)
        if current_len + seg_len > max_chars and current_segs:
            # Emit current chunk
            c_start = offsets[current_segs[0]][0]
            c_end = offsets[current_segs[-1]][1]
            content = text[c_start:c_end]
            chunks.append(
                Chunk(
                    content=content,
                    char_start=c_start,
                    char_end=c_end,
                    chunk_index=len(chunks),
                    token_count=len(content) // 4,
                )
            )
            current_segs = []
            current_len = 0

        current_segs.append(i)
        current_len += seg_len

    # Emit final chunk
    if current_segs:
        c_start = offsets[current_segs[0]][0]
        c_end = offsets[current_segs[-1]][1]
        content = text[c_start:c_end]
        chunks.append(
            Chunk(
                content=content,
                char_start=c_start,
                char_end=c_end,
                chunk_index=len(chunks),
                token_count=len(content) // 4,
            )
        )

    return chunks


def _chunk_fixed(text: str, max_chars: int, overlap_chars: int) -> list[Chunk]:
    """Fixed-size windows with overlap."""
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        content = text[start:end]
        chunks.append(
            Chunk(
                content=content,
                char_start=start,
                char_end=end,
                chunk_index=len(chunks),
                token_count=len(content) // 4,
            )
        )
        if end >= len(text):
            break
        start = end - overlap_chars
    return chunks


@dataclass(frozen=True)
class FileScan:
    """What a corpus would index, and why everything else was left out.

    Every path is absolute and each list is sorted. The three lists are disjoint
    and together they are the candidate set produced by ``corpus.include``.
    """

    included: list[Path]
    ignored: list[Path]
    dotpath: list[Path]


def find_markdown_files(root: Path, include: list[str] | None = None) -> list[Path]:
    """Find .md files under root, optionally scoped to include paths.

    If include is given, only search within those subdirectories (relative to root).
    Dotfile directories (starting with '.') are always excluded.
    """
    if include:
        files = []
        for pattern in include:
            sub = root / pattern
            if sub.is_dir():
                files.extend(sub.rglob("*.md"))
            elif sub.is_file() and sub.suffix == ".md":
                files.append(sub)
        return sorted(set(files))
    return sorted(root.rglob("*.md"))


def _is_dotpath(filepath: Path, root: Path) -> bool:
    """Check if any component of the relative path starts with '.'."""
    rel = filepath.relative_to(root)
    return any(part.startswith(".") for part in rel.parts)


def scan_corpus_files(root: Path, config: dict) -> FileScan:
    """Resolve which markdown files the corpus would index.

    Precedence is fixed: ``corpus.include`` scopes the candidates, ``.kgmdignore``
    subtracts from them and a negation re-adds, and the dot-path rule dominates
    both — no pattern, negated or otherwise, can re-admit a dotted path.

    This is the single source of the resolved file set: ingest and the dry-run
    preview both read it, so a preview cannot disagree with what a build does.
    """
    include = config.get("corpus", {}).get("include")
    candidates = find_markdown_files(root, include=include)
    rules = load_ignore_rules(root)

    included: list[Path] = []
    ignored: list[Path] = []
    dotpath: list[Path] = []
    for fpath in candidates:
        if _is_dotpath(fpath, root):
            dotpath.append(fpath)
        elif is_ignored(fpath.relative_to(root).as_posix(), rules):
            ignored.append(fpath)
        else:
            included.append(fpath)

    return FileScan(included=included, ignored=ignored, dotpath=dotpath)


def dry_run_report(conn, corpus_dir: Path, config: dict) -> dict:
    """The resolved file set behind `kgmd build --dry-run`. Never writes.

    ``conn`` may be None when the corpus has no database yet, in which case
    nothing can be pending removal. Paths are corpus-relative POSIX strings, the
    same form stored in ``documents.path``.
    """
    scan = scan_corpus_files(corpus_dir, config)

    def rel(paths: list[Path]) -> list[str]:
        return [p.relative_to(corpus_dir).as_posix() for p in paths]

    included = rel(scan.included)
    would_remove = 0
    if conn is not None:
        indexed = {row[0] for row in conn.execute("SELECT path FROM documents").fetchall()}
        would_remove = len(indexed - set(included))

    return {
        "included": included,
        "ignored": rel(scan.ignored),
        "dotpath": rel(scan.dotpath),
        "counts": {
            "included": len(scan.included),
            "ignored": len(scan.ignored),
            "dotpath": len(scan.dotpath),
            "would_remove": would_remove,
        },
    }


# SQLite caps host parameters per statement; bind ids in batches rather than
# creating a temp table, which would be DDL outside kgmd/schema.py.
_ID_BATCH = 500

REMOVAL_KEYS = (
    "documents_removed",
    "chunks_removed",
    "relations_removed",
    "entities_removed",
    "vectors_removed",
)


def prune_missing_documents(conn, kept_rel_paths: set[str]) -> dict:
    """Remove indexed documents whose path is no longer part of the corpus.

    Newly ignored, deleted, and renamed files are the same state — the recorded
    path is not in ``kept_rel_paths`` — and are handled identically.

    Cascades do not cover everything. ``entity_mentions`` follows its chunks, but
    ``relations.evidence_chunk_id`` is ON DELETE SET NULL and the sqlite-vec tables
    have no foreign keys at all, so relations bound to removed evidence and both
    vector tables are deleted explicitly. Leaving a vector behind would be worse
    than untidy: chunk and mention ids are reused, and ``embed_new_chunks`` skips
    any chunk that already has a vector row, so a future chunk would silently
    inherit the vector of deleted text.
    """
    stats = dict.fromkeys(REMOVAL_KEYS, 0)

    rows = conn.execute("SELECT id, path FROM documents").fetchall()
    if not rows:
        return stats

    orphan_ids = [row["id"] for row in rows if row["path"] not in kept_rel_paths]
    if not orphan_ids:
        return stats

    if not kept_rel_paths:
        raise RuntimeError(
            "Ignore rules exclude every markdown file in the corpus, but the graph still holds "
            f"{len(rows)} document(s). Refusing to empty it. Check .kgmdignore — "
            f"run 'kgmd build --dry-run' to see what would be indexed — or use "
            f"'kgmd reset --hard' if clearing the graph is what you meant."
        )

    # Collect ids before deleting anything: mention ids are unrecoverable once
    # their chunks are gone.
    chunk_ids = _ids_in(conn, "SELECT id FROM chunks WHERE document_id IN", orphan_ids)
    mention_ids = _ids_in(conn, "SELECT id FROM entity_mentions WHERE chunk_id IN", chunk_ids)
    entity_ids = _ids_in(
        conn, "SELECT DISTINCT entity_id FROM entity_mentions WHERE chunk_id IN", chunk_ids
    )

    stats["vectors_removed"] += _delete_in(
        conn, "DELETE FROM vec_entity_mentions WHERE mention_id IN", mention_ids
    )
    stats["vectors_removed"] += _delete_in(
        conn, "DELETE FROM vec_chunks WHERE chunk_id IN", chunk_ids
    )
    stats["relations_removed"] = _delete_in(
        conn, "DELETE FROM relations WHERE evidence_chunk_id IN", chunk_ids
    )
    stats["chunks_removed"] = _delete_in(
        conn, "DELETE FROM chunks WHERE document_id IN", orphan_ids
    )
    stats["documents_removed"] = _delete_in(conn, "DELETE FROM documents WHERE id IN", orphan_ids)
    stats["entities_removed"] = _sweep_orphan_entities(conn, entity_ids)

    conn.commit()
    return stats


def _sweep_orphan_entities(conn, entity_ids: list[int]) -> int:
    """Delete entities that this prune left with no mention and no relation.

    Scoped to the entities whose mentions were just removed, so pre-existing
    orphans left behind by 'kgmd extract --force' are not collected here.
    """
    return _delete_in(
        conn,
        "DELETE FROM entities WHERE id NOT IN (SELECT entity_id FROM entity_mentions)"
        " AND id NOT IN (SELECT subject_id FROM relations)"
        " AND id NOT IN (SELECT object_id FROM relations)"
        " AND id IN",
        entity_ids,
    )


def _batches(ids: list[int]):
    for start in range(0, len(ids), _ID_BATCH):
        yield ids[start : start + _ID_BATCH]


def _ids_in(conn, select_prefix: str, ids: list[int]) -> list[int]:
    """Run a `... IN (ids)` select over batched ids and collect the first column."""
    out: list[int] = []
    for batch in _batches(ids):
        placeholders = ",".join("?" * len(batch))
        rows = conn.execute(f"{select_prefix} ({placeholders})", batch).fetchall()
        out.extend(row[0] for row in rows)
    return out


def _delete_in(conn, delete_prefix: str, ids: list[int]) -> int:
    """Run a `... IN (ids)` delete over batched ids and total the affected rows."""
    removed = 0
    for batch in _batches(ids):
        placeholders = ",".join("?" * len(batch))
        cur = conn.execute(f"{delete_prefix} ({placeholders})", batch)
        removed += cur.rowcount
    return removed


def ingest_documents(conn, corpus_dir: Path, config: dict) -> dict:
    """Ingest markdown files: hash-check, upsert documents, chunk.

    Returns a summary dict with counts.
    """
    scan = scan_corpus_files(corpus_dir, config)
    md_files = scan.included

    chunking = config.get("chunking", {})
    max_chars = chunking.get("max_chars", 4000)
    overlap_chars = chunking.get("overlap_chars", 200)
    split_on = chunking.get("split_on", "paragraph")

    stats = {"new": 0, "updated": 0, "skipped": 0, "chunks_created": 0}
    stats.update(
        prune_missing_documents(conn, {p.relative_to(corpus_dir).as_posix() for p in scan.included})
    )
    now = datetime.now(timezone.utc).isoformat()

    for fpath in md_files:
        rel_path = str(fpath.relative_to(corpus_dir))
        content = fpath.read_text(encoding="utf-8")
        content_hash = hash_content(content)
        mtime = fpath.stat().st_mtime
        size_bytes = len(content.encode("utf-8"))

        # Check existing document
        row = conn.execute(
            "SELECT id, content_hash FROM documents WHERE path = ?", (rel_path,)
        ).fetchone()

        if row and row["content_hash"] == content_hash:
            stats["skipped"] += 1
            continue

        if row:
            doc_id = row["id"]
            conn.execute(
                "UPDATE documents SET content_hash=?, size_bytes=?,"
                " mtime=?, ingested_at=?,"
                " last_extracted_hash=NULL WHERE id=?",
                (content_hash, size_bytes, mtime, now, doc_id),
            )
            # Delete old chunks (cascades to mentions)
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
            stats["updated"] += 1
        else:
            cur = conn.execute(
                "INSERT INTO documents"
                " (path, content_hash, size_bytes, mtime, ingested_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (rel_path, content_hash, size_bytes, mtime, now),
            )
            doc_id = cur.lastrowid
            stats["new"] += 1

        # Chunk the document
        chunks = chunk_markdown(content, max_chars, overlap_chars, split_on)
        for chunk in chunks:
            conn.execute(
                "INSERT INTO chunks"
                " (document_id, chunk_index, content,"
                " char_start, char_end, token_count)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    doc_id,
                    chunk.chunk_index,
                    chunk.content,
                    chunk.char_start,
                    chunk.char_end,
                    chunk.token_count,
                ),
            )
            stats["chunks_created"] += 1

    conn.commit()
    return stats
