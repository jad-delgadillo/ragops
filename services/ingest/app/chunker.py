"""Text normalization and chunking with line-number tracking."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    """A chunk of text with metadata."""

    content: str
    chunk_index: int
    line_start: int
    line_end: int
    token_count: int = 0
    source_file: str = ""


def normalize_text(text: str) -> str:
    """Normalize text: strip control chars, normalize whitespace."""
    # Replace \r\n with \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Remove non-printable control characters (keep newlines, tabs)
    text = re.sub(r"[^\x09\x0a\x20-\x7e\x80-\xff]", "", text)
    # Collapse multiple blank lines into two
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token for English)."""
    return max(1, len(text) // 4)


def chunk_text(
    text: str,
    *,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    source_file: str = "",
) -> list[Chunk]:
    """Split text into overlapping chunks with line-number tracking.

    Args:
        text: The full text to chunk.
        chunk_size: Target chunk size in tokens (approximate).
        chunk_overlap: Overlap between chunks in tokens.
        source_file: Source file path for metadata.

    Returns:
        List of Chunk objects.
    """
    if not text.strip():
        return []

    chunks: list[Chunk] = []
    chunk_index = 0

    # Convert token counts to approximate character counts
    char_size = chunk_size * 4
    char_overlap = chunk_overlap * 4

    current_pos = 0
    text_len = len(text)

    while current_pos < text_len:
        # Determine chunk end
        end_pos = min(current_pos + char_size, text_len)

        # Try to break at a paragraph or sentence boundary
        if end_pos < text_len:
            # Look for paragraph break
            para_break = text.rfind("\n\n", current_pos + char_size // 2, end_pos)
            if para_break != -1:
                end_pos = para_break + 1
            else:
                # Look for sentence break
                sentence_break = text.rfind(". ", current_pos + char_size // 2, end_pos)
                if sentence_break != -1:
                    end_pos = sentence_break + 2
                else:
                    # Look for line break
                    line_break = text.rfind("\n", current_pos + char_size // 2, end_pos)
                    if line_break != -1:
                        end_pos = line_break + 1

        chunk_text_content = text[current_pos:end_pos].strip()
        if not chunk_text_content:
            break

        # Calculate line numbers
        line_start = text[:current_pos].count("\n") + 1
        line_end = text[:end_pos].count("\n") + 1

        chunks.append(
            Chunk(
                content=chunk_text_content,
                chunk_index=chunk_index,
                line_start=line_start,
                line_end=line_end,
                token_count=estimate_tokens(chunk_text_content),
                source_file=source_file,
            )
        )

        chunk_index += 1

        # If this chunk reached the end of text, we're done
        if end_pos >= text_len:
            break

        # Move forward by (chunk_size - overlap)
        advance = end_pos - current_pos - char_overlap
        current_pos = current_pos + max(advance, 1)

    return chunks
