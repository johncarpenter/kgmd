"""Embedding backend: fastembed wrapper + litellm API fallback."""

from __future__ import annotations

from typing import Protocol

from rich.progress import Progress


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def get_dimension(self) -> int: ...
    def model_id(self) -> str: ...


class FastembedEmbedder:
    """Wraps fastembed.TextEmbedding for local CPU-based embeddings."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding

        self._model_name = model_name
        self._model = TextEmbedding(model_name=model_name)
        # Determine dimension from a probe
        probe = list(self._model.embed(["test"]))[0]
        self._dim = len(probe)

    def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        batch_size = 64
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = list(self._model.embed(batch))
            results.extend([e.tolist() for e in embeddings])
        return results

    def get_dimension(self) -> int:
        return self._dim

    def model_id(self) -> str:
        return self._model_name


class LitellmEmbedder:
    """Wraps litellm.embedding for API-based embeddings."""

    def __init__(self, model_name: str = "text-embedding-3-small"):
        self._model_name = model_name
        self._dim: int | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        import litellm

        results = []
        batch_size = 96
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = litellm.embedding(model=self._model_name, input=batch)
            for item in resp.data:
                vec = item["embedding"]
                if self._dim is None:
                    self._dim = len(vec)
                results.append(vec)
        return results

    def get_dimension(self) -> int:
        if self._dim is None:
            # Probe with a dummy call
            self.embed(["test"])
        return self._dim  # type: ignore[return-value]

    def model_id(self) -> str:
        return self._model_name


def get_embedder(config: dict) -> Embedder:
    """Create an embedder from config."""
    emb_cfg = config.get("embedding", {})
    backend = emb_cfg.get("backend", "fastembed")
    model = emb_cfg.get("model", "BAAI/bge-small-en-v1.5")

    if backend == "litellm":
        return LitellmEmbedder(model)
    return FastembedEmbedder(model)


def embed_new_chunks(conn, embedder: Embedder) -> int:
    """Embed chunks that don't yet have embeddings in vec_chunks."""
    rows = conn.execute(
        """SELECT c.id, c.content FROM chunks c
           WHERE c.id NOT IN (SELECT chunk_id FROM vec_chunks)"""
    ).fetchall()

    if not rows:
        return 0

    ids = [r["id"] for r in rows]
    texts = [r["content"] for r in rows]

    with Progress() as progress:
        task = progress.add_task("Embedding chunks", total=len(texts))
        batch_size = 64
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            batch_ids = ids[i : i + batch_size]
            embeddings = embedder.embed(batch_texts)
            for chunk_id, vec in zip(batch_ids, embeddings):
                conn.execute(
                    "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
                    (chunk_id, _serialize_vec(vec)),
                )
            progress.advance(task, len(batch_texts))

    conn.commit()
    return len(ids)


def embed_new_mentions(conn, embedder: Embedder) -> int:
    """Embed entity mentions that don't yet have embeddings in vec_entity_mentions."""
    rows = conn.execute(
        """SELECT em.id, em.surface_form FROM entity_mentions em
           WHERE em.id NOT IN (SELECT mention_id FROM vec_entity_mentions)"""
    ).fetchall()

    if not rows:
        return 0

    ids = [r["id"] for r in rows]
    texts = [r["surface_form"] for r in rows]

    with Progress() as progress:
        task = progress.add_task("Embedding mentions", total=len(texts))
        batch_size = 64
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            batch_ids = ids[i : i + batch_size]
            embeddings = embedder.embed(batch_texts)
            for mention_id, vec in zip(batch_ids, embeddings):
                conn.execute(
                    "INSERT INTO vec_entity_mentions (mention_id, embedding) VALUES (?, ?)",
                    (mention_id, _serialize_vec(vec)),
                )
            progress.advance(task, len(batch_texts))

    conn.commit()
    return len(ids)


def _serialize_vec(vec: list[float]) -> bytes:
    """Serialize a float vector to bytes for sqlite-vec."""
    import struct

    return struct.pack(f"{len(vec)}f", *vec)
