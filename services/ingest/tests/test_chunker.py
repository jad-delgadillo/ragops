"""Unit tests for the text chunker."""

from services.ingest.app.chunker import chunk_text, estimate_tokens, normalize_text


class TestNormalizeText:
    def test_strips_control_chars(self):
        text = "hello\x00world\x01test"
        result = normalize_text(text)
        assert "\x00" not in result
        assert "\x01" not in result

    def test_normalizes_line_endings(self):
        text = "line1\r\nline2\rline3\n"
        result = normalize_text(text)
        assert "\r" not in result
        assert result == "line1\nline2\nline3"

    def test_collapses_blank_lines(self):
        text = "para1\n\n\n\n\npara2"
        result = normalize_text(text)
        assert result == "para1\n\npara2"

    def test_strips_whitespace(self):
        result = normalize_text("  hello  ")
        assert result == "hello"

    def test_empty_string(self):
        assert normalize_text("") == ""


class TestEstimateTokens:
    def test_basic_estimate(self):
        # ~4 chars per token
        assert estimate_tokens("a" * 100) == 25

    def test_minimum_one(self):
        assert estimate_tokens("hi") >= 1

    def test_empty(self):
        assert estimate_tokens("") >= 1


class TestChunkText:
    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_single_small_chunk(self):
        text = "This is a very short document."
        chunks = chunk_text(text, chunk_size=100)
        assert len(chunks) == 1
        assert chunks[0].content == text
        assert chunks[0].chunk_index == 0
        assert chunks[0].line_start == 1

    def test_multiple_chunks(self):
        # Create text that will produce multiple chunks
        text = "\n".join([f"Line {i}: " + "x" * 100 for i in range(50)])
        chunks = chunk_text(text, chunk_size=50, chunk_overlap=5)
        assert len(chunks) > 1
        # Verify chunk indices are sequential
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_line_tracking(self):
        text = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        chunks = chunk_text(text, chunk_size=1000)
        assert len(chunks) == 1
        assert chunks[0].line_start == 1
        assert chunks[0].line_end >= 5

    def test_source_file_metadata(self):
        text = "Some content here."
        chunks = chunk_text(text, source_file="docs/readme.md")
        assert chunks[0].source_file == "docs/readme.md"

    def test_token_count(self):
        text = "A" * 400  # ~100 tokens
        chunks = chunk_text(text, chunk_size=1000)
        assert chunks[0].token_count > 0
