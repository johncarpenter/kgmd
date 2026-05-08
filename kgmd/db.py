"""SQLite + sqlite-vec connection management and migrations."""

from __future__ import annotations

import fcntl
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

from kgmd.schema import KV_DEFAULTS, SCHEMA_SQL, vec_tables_sql


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a connection to the kgmd database with required pragmas and extensions."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(db_path: Path, embedding_dim: int = 384) -> sqlite3.Connection:
    """Create or open the database and ensure the schema exists."""
    conn = get_connection(db_path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(vec_tables_sql(embedding_dim))
        # Seed kv defaults
        for k, v in KV_DEFAULTS.items():
            if k == "embedding_dim":
                v = str(embedding_dim)
            conn.execute("INSERT OR IGNORE INTO kv (key, value) VALUES (?, ?)", (k, v))
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
    return conn


def check_embedding_model(conn: sqlite3.Connection, model_id: str) -> None:
    """Raise if the db was initialized with a different embedding model."""
    row = conn.execute("SELECT value FROM kv WHERE key = 'embedding_model'").fetchone()
    if row and row[0] != model_id:
        raise RuntimeError(
            f"Database was initialized with embedding model '{row[0]}', "
            f"but config specifies '{model_id}'. Changing embedding models "
            f"mid-corpus is not supported in v1. To re-embed, delete .kgmd/graph.db "
            f"and rebuild."
        )


@contextmanager
def build_lock(kgmd_dir: Path):
    """Acquire an exclusive file lock for build operations."""
    lock_path = kgmd_dir / "build.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Check if holder PID is still alive
            content = os.read(fd, 64)
            if content:
                try:
                    pid = int(content.strip())
                    os.kill(pid, 0)  # Check if alive
                    raise RuntimeError(
                        f"Another kgmd build process (PID {pid}) is running. "
                        f"If this is stale, delete .kgmd/build.lock"
                    )
                except (ValueError, ProcessLookupError):
                    # Stale lock — reclaim
                    fcntl.flock(fd, fcntl.LOCK_EX)
            else:
                raise RuntimeError(
                    "Another kgmd build process holds the lock. "
                    "If this is stale, delete .kgmd/build.lock"
                )
        # Write our PID
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.ftruncate(fd, 0)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        try:
            os.unlink(str(lock_path))
        except OSError:
            pass
