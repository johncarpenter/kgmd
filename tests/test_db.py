"""Tests for database schema creation, migrations, and vec extension."""


from kgmd.db import init_db


def test_schema_creation(tmp_path):
    """Test that init_db creates all tables."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]

    assert "documents" in tables
    assert "chunks" in tables
    assert "entities" in tables
    assert "entity_mentions" in tables
    assert "relations" in tables
    assert "extraction_runs" in tables
    assert "resolution_runs" in tables
    assert "schema_versions" in tables
    assert "kv" in tables
    conn.close()


def test_vec_extension_loaded(tmp_path):
    """Test that sqlite-vec extension is loaded."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    version = conn.execute("SELECT vec_version()").fetchone()[0]
    assert version.startswith("v")
    conn.close()


def test_vec_tables_created(tmp_path):
    """Test that virtual vector tables exist."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]

    assert "vec_chunks" in tables
    assert "vec_entity_mentions" in tables
    conn.close()


def test_pragmas_set(tmp_path):
    """Test that required pragmas are set."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal == "wal"

    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
    conn.close()


def test_user_version(tmp_path):
    """Test that user_version is set to 1 after init."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1
    conn.close()


def test_idempotent_init(tmp_path):
    """Test that init_db is idempotent."""
    db_path = tmp_path / "test.db"
    conn1 = init_db(db_path)
    conn1.close()

    conn2 = init_db(db_path)
    version = conn2.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1
    conn2.close()


def test_kv_defaults(tmp_path):
    """Test that kv table has default values."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    dim = conn.execute("SELECT value FROM kv WHERE key = 'embedding_dim'").fetchone()[0]
    assert dim == "384"

    model = conn.execute("SELECT value FROM kv WHERE key = 'embedding_model'").fetchone()[0]
    assert model == "BAAI/bge-small-en-v1.5"

    sv = conn.execute("SELECT value FROM kv WHERE key = 'schema_version'").fetchone()[0]
    assert sv == "1"
    conn.close()


def test_custom_embedding_dim(tmp_path):
    """Test that custom embedding dimension is used."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path, embedding_dim=768)

    dim = conn.execute("SELECT value FROM kv WHERE key = 'embedding_dim'").fetchone()[0]
    assert dim == "768"
    conn.close()
