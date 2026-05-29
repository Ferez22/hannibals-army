"""Text chunking for document RAG.

Semantic-first split:
  - PDF/PPTX: split on form-feed / "## Slide" boundaries when present
  - Else: paragraph split, then size-based merge with overlap.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Approximate token count → ~4 chars per token, fits gemma4 context comfortably
CHAT_CHUNK_CHARS = 1200
CHAT_CHUNK_OVERLAP = 200


@dataclass
class Chunk:
    ordinal: int
    text: str
    char_start: int
    char_end: int


def chunk_text(text: str) -> list[Chunk]:
    text = text.strip()
    if not text:
        return []

    # Semantic blocks first — slide/page markers from parsers
    semantic_blocks = _split_semantic(text)
    chunks: list[Chunk] = []
    ordinal = 0

    for block_text, block_start in semantic_blocks:
        size_chunks = _split_by_size(block_text)
        for sc_text, sc_start, sc_end in size_chunks:
            chunks.append(
                Chunk(
                    ordinal=ordinal,
                    text=sc_text,
                    char_start=block_start + sc_start,
                    char_end=block_start + sc_end,
                )
            )
            ordinal += 1
    return chunks


def _split_semantic(text: str) -> list[tuple[str, int]]:
    """Return list of (block_text, absolute_offset_in_text)."""
    parts: list[tuple[str, int]] = []
    pattern = re.compile(r"(^|\n)## (?:Slide|Page|Sheet) ", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return [(text, 0)]
    for i, m in enumerate(matches):
        start = m.start() + (1 if m.group(1) == "\n" else 0)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if block:
            parts.append((block, start))
    return parts


def _split_by_size(text: str) -> list[tuple[str, int, int]]:
    """Greedy paragraph-aware chunking with overlap. Returns (chunk, start, end)."""
    if len(text) <= CHAT_CHUNK_CHARS:
        return [(text, 0, len(text))]

    chunks: list[tuple[str, int, int]] = []
    paragraphs = re.split(r"\n\s*\n", text)
    para_offsets: list[int] = []
    pos = 0
    for para in paragraphs:
        para_offsets.append(pos)
        pos += len(para) + 2  # the split eats "\n\n"

    buf: list[str] = []
    buf_start: int | None = None
    buf_len = 0
    for para, offset in zip(paragraphs, para_offsets):
        if buf_start is None:
            buf_start = offset
        if buf_len + len(para) + 2 > CHAT_CHUNK_CHARS and buf:
            chunk_text_str = "\n\n".join(buf).strip()
            chunks.append((chunk_text_str, buf_start, buf_start + len(chunk_text_str)))
            # Overlap: keep tail
            tail = chunk_text_str[-CHAT_CHUNK_OVERLAP:] if len(chunk_text_str) > CHAT_CHUNK_OVERLAP else chunk_text_str
            buf = [tail, para]
            buf_start = offset - len(tail)
            buf_len = len(tail) + len(para) + 2
        else:
            buf.append(para)
            buf_len += len(para) + 2

    if buf:
        chunk_text_str = "\n\n".join(buf).strip()
        chunks.append((chunk_text_str, buf_start or 0, (buf_start or 0) + len(chunk_text_str)))
    return chunks
