"""Chunking: splits pages into overlapping word windows with heading hints."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

CHUNK_WORDS = 180
OVERLAP_WORDS = 30
MIN_TAIL_WORDS = 40


@dataclass(slots=True)
class Chunk:
    id: str
    doc_id: str
    filename: str
    page: int
    heading: str
    text: str
    n_tokens: int


_MD_HEADING = re.compile(r"^#{1,6}\s+(\S.*)$")
_NUM_HEADING = re.compile(r"^(?:\d+(?:\.\d+){0,4}\.?|[IVXL]+\.|[A-Z]\.)\s+([A-Z0-9][^\n]*)$")
_SMALL_WORDS = {
    "a", "an", "the", "of", "and", "or", "in", "on", "for", "to", "at", "by",
    "with", "from", "vs", "as", "is", "are", "its", "into", "over", "per",
}


def detect_heading(line: str) -> str | None:
    """Return the heading text if `line` looks like a heading, else None."""
    s = line.strip()
    if len(s) < 3 or len(s) > 90:
        return None
    m = _MD_HEADING.match(s)
    if m:
        return m.group(1).strip().strip("#").strip()[:90] or None
    words = s.split()
    if len(words) > 12:
        return None
    if s[-1] in ".,;:!?":
        return None
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 3:
        return None
    # Mostly digits or symbols (table rows, page numbers) are not headings.
    if len(letters) < len(s) * 0.5:
        m = _NUM_HEADING.match(s)
        if not m:
            return None
    m = _NUM_HEADING.match(s)
    if m and len(words) <= 10:
        return s
    if s.isupper() and len(words) <= 10:
        return s
    if 2 <= len(words) <= 8 and len(s) <= 70:
        sig = [w for w in words if w.lower() not in _SMALL_WORDS]
        if sig and all(w[0].isupper() for w in sig if w[0].isalpha()) and words[0][0].isupper():
            # Reject lines that contain sentence-like digits mixed with text
            if not re.search(r"\d{3,}", s):
                return s
    return None


def _page_words(text: str, carry: str) -> tuple[list[str], list[str], str]:
    """Return (words, heading per word, heading at end of page)."""
    words: list[str] = []
    heads: list[str] = []
    current = carry
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        h = detect_heading(line)
        if h:
            current = h
        lw = line.split()
        words.extend(lw)
        heads.extend([current] * len(lw))
    return words, heads, current


def chunk_pages(pages: Iterator[tuple[int, str]], doc_id: str, filename: str) -> Iterator[Chunk]:
    """Lazily turn pages into chunks. Never crosses a page boundary."""
    n = 0
    carry = ""
    for page, text in pages:
        words, heads, carry = _page_words(text, carry)
        total = len(words)
        if total == 0:
            continue
        start = 0
        while start < total:
            end = min(start + CHUNK_WORDS, total)
            if total - end < MIN_TAIL_WORDS:
                end = total
            piece = words[start:end]
            yield Chunk(
                id=f"{doc_id}-{n}",
                doc_id=doc_id,
                filename=filename,
                page=page,
                heading=heads[start],
                text=" ".join(piece),
                n_tokens=int(len(piece) * 1.3),
            )
            n += 1
            if end >= total:
                break
            start = end - OVERLAP_WORDS
