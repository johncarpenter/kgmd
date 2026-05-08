"""Markdown reading, chunking, and hashing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


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


def ingest_documents(conn, corpus_dir: Path, config: dict) -> dict:
    """Ingest markdown files: hash-check, upsert documents, chunk.

    Returns a summary dict with counts.
    """
    include = config.get("corpus", {}).get("include")
    md_files = find_markdown_files(corpus_dir, include=include)
    # Exclude dotfile directories (.kgmd, .claude, .git, etc.)
    md_files = [f for f in md_files if not _is_dotpath(f, corpus_dir)]

    chunking = config.get("chunking", {})
    max_chars = chunking.get("max_chars", 4000)
    overlap_chars = chunking.get("overlap_chars", 200)
    split_on = chunking.get("split_on", "paragraph")

    stats = {"new": 0, "updated": 0, "skipped": 0, "chunks_created": 0}
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
                "UPDATE documents SET content_hash=?, size_bytes=?, mtime=?, ingested_at=?, last_extracted_hash=NULL WHERE id=?",
                (content_hash, size_bytes, mtime, now, doc_id),
            )
            # Delete old chunks (cascades to mentions)
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
            stats["updated"] += 1
        else:
            cur = conn.execute(
                "INSERT INTO documents (path, content_hash, size_bytes, mtime, ingested_at) VALUES (?, ?, ?, ?, ?)",
                (rel_path, content_hash, size_bytes, mtime, now),
            )
            doc_id = cur.lastrowid
            stats["new"] += 1

        # Chunk the document
        chunks = chunk_markdown(content, max_chars, overlap_chars, split_on)
        for chunk in chunks:
            conn.execute(
                "INSERT INTO chunks (document_id, chunk_index, content, char_start, char_end, token_count) VALUES (?, ?, ?, ?, ?, ?)",
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
