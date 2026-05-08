"""Tests for markdown chunking."""

from kgmd.ingest import chunk_markdown


def test_paragraph_chunking():
    """Test paragraph-based chunking."""
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = chunk_markdown(text, max_chars=50, overlap_chars=0, split_on="paragraph")

    assert len(chunks) >= 1
    # All text should be covered
    full_text = "".join(c.content for c in chunks)
    assert "First paragraph." in full_text
    assert "Third paragraph." in full_text


def test_paragraph_chunking_offsets():
    """Test that character offsets are correct."""
    text = "Hello world.\n\nThis is a test.\n\nEnd of text."
    chunks = chunk_markdown(text, max_chars=1000, split_on="paragraph")

    assert len(chunks) == 1
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == len(text)
    assert text[chunks[0].char_start : chunks[0].char_end] == text


def test_heading_chunking():
    """Test heading-based chunking."""
    text = "# Title\n\nIntro text.\n\n## Section 1\n\nContent 1.\n\n## Section 2\n\nContent 2."
    chunks = chunk_markdown(text, max_chars=40, split_on="heading")

    assert len(chunks) >= 2
    assert any("Title" in c.content for c in chunks)
    assert any("Section 2" in c.content for c in chunks)


def test_fixed_chunking():
    """Test fixed-size chunking with overlap."""
    text = "A" * 100
    chunks = chunk_markdown(text, max_chars=30, overlap_chars=10, split_on="fixed")

    assert len(chunks) >= 3
    # First chunk starts at 0
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == 30
    # Second chunk overlaps
    assert chunks[1].char_start == 20
    assert chunks[1].char_end == 50


def test_empty_text():
    """Test that empty text produces no chunks."""
    chunks = chunk_markdown("", max_chars=100, split_on="paragraph")
    assert chunks == []

    chunks = chunk_markdown("   \n\n  ", max_chars=100, split_on="paragraph")
    assert chunks == []


def test_single_paragraph():
    """Test text with a single paragraph."""
    text = "Just one paragraph with some text."
    chunks = chunk_markdown(text, max_chars=1000, split_on="paragraph")

    assert len(chunks) == 1
    assert chunks[0].content == text


def test_chunk_index_sequential():
    """Test that chunk indices are sequential starting from 0."""
    text = "A\n\nB\n\nC\n\nD\n\nE"
    chunks = chunk_markdown(text, max_chars=5, split_on="paragraph")

    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i


def test_token_count_approximate():
    """Test that token_count is approximately len/4."""
    text = "Hello world this is a test document with some words."
    chunks = chunk_markdown(text, max_chars=1000, split_on="paragraph")

    assert len(chunks) == 1
    expected = len(text) // 4
    assert chunks[0].token_count == expected


def test_large_paragraph_not_split():
    """Test that a single paragraph larger than max_chars becomes one chunk."""
    text = "A" * 5000
    chunks = chunk_markdown(text, max_chars=4000, split_on="paragraph")

    assert len(chunks) == 1
    assert len(chunks[0].content) == 5000
