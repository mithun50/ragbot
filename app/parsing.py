"""Document parsing: turns files into a lazy stream of (page_number, text).

Nothing here holds a full document in memory. PDFs are read page by page,
DOCX files are walked in document order, and text-like files are read
incrementally and cut into synthetic pages of about PAGE_CHARS characters.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Iterator

PAGE_CHARS = 3000

TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".json"}
HTML_EXTS = {".html", ".htm"}
SUPPORTED_EXTS = TEXT_EXTS | HTML_EXTS | {".pdf", ".docx"}


class ParseError(Exception):
    """Raised for unsupported or unreadable documents. str(e) is user readable."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _ext(path: Path, filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if not ext:
        ext = Path(path).suffix.lower()
    return ext


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(text: str) -> str:
    text = _CTRL_RE.sub(" ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


# ---------------------------------------------------------------------------
# Pagination helper for non-PDF formats
# ---------------------------------------------------------------------------

def _split_long(block: str, limit: int) -> Iterator[str]:
    """Split an oversized block at whitespace near `limit` characters."""
    while len(block) > limit:
        cut = block.rfind(" ", int(limit * 0.6), limit)
        if cut == -1:
            cut = block.rfind("\n", int(limit * 0.6), limit)
        if cut == -1:
            cut = limit
        yield block[:cut].strip()
        block = block[cut:].lstrip()
    if block.strip():
        yield block.strip()


def _paginate(blocks: Iterable[str], limit: int = PAGE_CHARS) -> Iterator[tuple[int, str]]:
    """Group paragraph blocks into synthetic pages of about `limit` characters."""
    page_no = 0
    buf: list[str] = []
    size = 0
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        for piece in _split_long(block, limit):
            if buf and size + len(piece) > limit:
                page_no += 1
                yield page_no, "\n\n".join(buf)
                buf, size = [], 0
            buf.append(piece)
            size += len(piece) + 2
    if buf:
        page_no += 1
        yield page_no, "\n\n".join(buf)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _open_pdf(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise ParseError("PDF support is not installed (pypdf missing).") from e
    try:
        reader = PdfReader(str(path))
    except Exception as e:
        raise ParseError(f"This PDF could not be read ({type(e).__name__}). It may be corrupt.") from e
    if reader.is_encrypted:
        ok = 0
        try:
            ok = reader.decrypt("")
        except Exception:
            ok = 0
        if not ok:
            raise ParseError("This PDF is password protected. Remove the password and upload it again.")
    return reader


def _iter_pdf(path: Path) -> Iterator[tuple[int, str]]:
    reader = _open_pdf(path)
    try:
        total = len(reader.pages)
    except Exception as e:
        raise ParseError(f"This PDF could not be read ({type(e).__name__}). It may be corrupt.") from e
    found = 0
    for i in range(total):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception:
            text = ""
        text = _clean(text)
        # Drop cached objects so memory stays flat on very large files.
        try:
            cache = getattr(reader, "_cached_objects", None)
            if cache is not None and i % 50 == 49:
                cache.clear()
        except Exception:
            pass
        if text:
            found += 1
            yield i + 1, text
    if found == 0:
        raise ParseError(
            "No text could be extracted from this PDF. It looks scanned or has no text layer. "
            "Run OCR on it and upload again."
        )


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def _iter_docx_blocks(path: Path) -> Iterator[str]:
    try:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as e:  # pragma: no cover
        raise ParseError("DOCX support is not installed (python-docx missing).") from e
    try:
        document = docx.Document(str(path))
    except Exception as e:
        raise ParseError(f"This DOCX could not be read ({type(e).__name__}). It may be corrupt.") from e

    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, document)
            text = _clean(para.text)
            if not text:
                continue
            style = (para.style.name if para.style is not None else "") or ""
            if style.lower().startswith("heading") or style.lower() == "title":
                level = 1
                m = re.search(r"(\d+)", style)
                if m:
                    level = max(1, min(6, int(m.group(1))))
                text = "#" * level + " " + text
            yield text
        elif tag == "tbl":
            table = Table(child, document)
            rows: list[str] = []
            for row in table.rows:
                cells: list[str] = []
                seen: set[int] = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    t = _clean(cell.text).replace("\n", " ")
                    if t:
                        cells.append(t)
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                yield "\n".join(rows)


def _iter_docx(path: Path) -> Iterator[tuple[int, str]]:
    found = False
    for page in _paginate(_iter_docx_blocks(path)):
        found = True
        yield page
    if not found:
        raise ParseError("This DOCX contains no text.")


# ---------------------------------------------------------------------------
# Plain text and HTML
# ---------------------------------------------------------------------------

def _detect_encoding(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(4)
        if head.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        if head.startswith((b"\xff\xfe", b"\xfe\xff")):
            return "utf-16"
        f.seek(0)
        sample = f.read(1 << 20)
    try:
        sample.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError as e:
        # A cut multi-byte char at the sample boundary is not a real error.
        if e.start >= len(sample) - 4:
            return "utf-8"
    return "cp1252"


def _iter_text_blocks(path: Path) -> Iterator[str]:
    """Yield paragraphs (blank-line separated) streaming from disk."""
    enc = _detect_encoding(path)
    buf: list[str] = []
    with open(path, "r", encoding=enc, errors="replace", newline=None) as f:
        for line in f:
            if line.strip():
                buf.append(line.rstrip("\n"))
                if sum(len(x) for x in buf) > PAGE_CHARS * 2:
                    # A paragraph with no blank lines (CSV, JSON, logs): flush it.
                    yield _clean("\n".join(buf))
                    buf = []
            elif buf:
                yield _clean("\n".join(buf))
                buf = []
        if buf:
            yield _clean("\n".join(buf))


class _TextExtractor(HTMLParser):
    BLOCK = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "header", "footer", "table", "ul", "ol", "pre", "blockquote",
    }
    SKIP = {"script", "style", "noscript", "head", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n\n" if tag.startswith("h") or tag in ("p", "div", "section", "article") else "\n")
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                self.parts.append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _iter_html_blocks(path: Path) -> Iterator[str]:
    enc = _detect_encoding(path)
    with open(path, "r", encoding=enc, errors="replace") as f:
        raw = f.read()
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        pass
    text = "".join(parser.parts)
    del raw
    for block in re.split(r"\n\s*\n", text):
        block = _clean(re.sub(r"[ \t]+", " ", block))
        if block:
            yield block


def _iter_plain(path: Path, ext: str) -> Iterator[tuple[int, str]]:
    blocks = _iter_html_blocks(path) if ext in HTML_EXTS else _iter_text_blocks(path)
    found = False
    for page in _paginate(blocks):
        found = True
        yield page
    if not found:
        raise ParseError("This file contains no text.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def iter_pages(path: Path, filename: str) -> Iterator[tuple[int, str]]:
    """Yield (page_number starting at 1, text). Empty pages are skipped."""
    path = Path(path)
    ext = _ext(path, filename)
    if ext not in SUPPORTED_EXTS:
        shown = ext or "(no extension)"
        raise ParseError(f"Unsupported file type {shown} for {filename}.")
    if ext == ".pdf":
        return _iter_pdf(path)
    if ext == ".docx":
        return _iter_docx(path)
    return _iter_plain(path, ext)


def count_pages(path: Path, filename: str) -> int | None:
    """Cheap page count for PDFs, None for other formats or on any failure."""
    if _ext(Path(path), filename) != ".pdf":
        return None
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return None
        return len(reader.pages)
    except Exception:
        return None
