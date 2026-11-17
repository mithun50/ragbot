"""In-memory BM25 store with an inverted index and per-document JSON persistence.

Layout per document: a list of Chunk objects, a list of chunk lengths and an
inverted index mapping term -> array('Q') of packed postings (chunk_idx << 8 | tf).
Packed arrays keep memory small (8 bytes per posting) even for 100k+ chunks.
Search only touches the postings of the query terms, never every chunk.
"""

from __future__ import annotations

import heapq
import json
import math
import os
import re
import threading
import uuid
from array import array
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.chunking import Chunk

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = DATA_DIR / "docs"
UPLOADS_DIR = DATA_DIR / "uploads"

K1 = 1.5
B = 0.75
TERMINAL = ("ready", "error")

STOPWORDS = frozenset(
    """a an the and or but if of to in on at by for with from as is are was were be been being
    it its this that these those there here he she they them we you i me my our your his her
    what which who whom whose when where why how do does did done doing have has had having
    can could should would will shall may might must not no nor so than then too very just
    about into over under per via also any all some such own same other more most
    tell say says said please give show explain describe document doc""".split()
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_stem_cache: dict[str, str] = {}
_VOWELS = "aeiou"


def _stem(w: str) -> str:
    cached = _stem_cache.get(w)
    if cached is not None:
        return cached
    s = w
    n = len(s)
    if n > 3 and not s.isdigit():
        if s.endswith("ies") and n > 4:
            s = s[:-3] + "y"
        elif s.endswith(("sses", "xes", "ches", "shes", "zes")) and n > 4:
            s = s[:-2]
        elif s.endswith("ing") and n > 5:
            s = s[:-3]
            if len(s) > 2 and s[-1] == s[-2] and s[-1] not in _VOWELS + "lsz":
                s = s[:-1]
        elif s.endswith("ed") and n > 4:
            s = s[:-2]
            if len(s) > 2 and s[-1] == s[-2] and s[-1] not in _VOWELS + "lsz":
                s = s[:-1]
        elif s.endswith("s") and not s.endswith(("ss", "us", "is")):
            s = s[:-1]
        if len(s) > 4 and s.endswith("e"):
            s = s[:-1]
    if len(_stem_cache) > 300_000:
        _stem_cache.clear()
    _stem_cache[w] = s
    return s


_COMPOUND_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")


def tokenize(text: str) -> list[str]:
    low = text.lower()
    out = []
    for w in _WORD_RE.findall(low):
        if w in STOPWORDS or len(w) > 40:
            continue
        out.append(_stem(w))
    # Keep hyphenated names whole (helios-a, tn-0040) so one-letter suffixes still tell entities apart.
    for c in _COMPOUND_RE.findall(low):
        if len(c) <= 40:
            out.append(c)
    return out


@dataclass(slots=True)
class Hit:
    chunk: Chunk
    score: float
    norm: float


class _Doc:
    __slots__ = ("meta", "chunks", "lens", "inv", "total_len")

    def __init__(self, meta: dict):
        self.meta = meta
        self.chunks: list[Chunk] = []
        self.lens: list[int] = []
        self.inv: dict[str, array] = {}
        self.total_len = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _term_freqs(text: str) -> tuple[dict[str, int], int]:
    toks = tokenize(text)
    tf: dict[str, int] = {}
    for t in toks:
        tf[t] = tf.get(t, 0) + 1
    return tf, len(toks)


class Store:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._docs: dict[str, _Doc] = {}
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_all()

    # ------------------------------------------------------------------ docs
    def create_doc(self, filename: str, size_bytes: int) -> dict:
        with self._lock:
            doc_id = uuid.uuid4().hex[:8]
            while doc_id in self._docs:
                doc_id = uuid.uuid4().hex[:8]
            meta = {
                "id": doc_id,
                "filename": filename,
                "size_bytes": int(size_bytes),
                "status": "queued",
                "pages_total": 0,
                "pages_done": 0,
                "chunks": 0,
                "words": 0,
                "error": None,
                "summary": "",
                "key_facts": [],
                "suggested_questions": [],
                "created_at": _now(),
            }
            self._docs[doc_id] = _Doc(meta)
            return dict(meta)

    def update_doc(self, doc_id: str, **fields) -> dict | None:
        persist = False
        with self._lock:
            d = self._docs.get(doc_id)
            if d is None:
                return None
            d.meta.update(fields)
            if d.meta.get("status") != "error":
                d.meta["error"] = d.meta.get("error") if fields.get("error") else None
            if d.meta.get("status") in TERMINAL and ("status" in fields or "summary" in fields):
                persist = True
            snap = self._snapshot(d) if persist else None
            out = dict(d.meta)
        if snap is not None:
            self._write_snapshot(doc_id, snap)
        return out

    def add_chunks(self, doc_id: str, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        # Tokenise outside the lock so searches are never blocked by parsing.
        prepared = [(c, *_term_freqs(c.text)) for c in chunks]
        with self._lock:
            d = self._docs.get(doc_id)
            if d is None:
                return
            inv = d.inv
            for chunk, tf, length in prepared:
                idx = len(d.chunks)
                d.chunks.append(chunk)
                d.lens.append(length)
                d.total_len += length
                for term, f in tf.items():
                    packed = (idx << 8) | (f if f < 255 else 255)
                    arr = inv.get(term)
                    if arr is None:
                        inv[term] = array("Q", (packed,))
                    else:
                        arr.append(packed)

    def finalize(self, doc_id: str) -> None:
        with self._lock:
            d = self._docs.get(doc_id)
            if d is None:
                return
            d.meta["chunks"] = len(d.chunks)
            snap = self._snapshot(d)
        self._write_snapshot(doc_id, snap)

    def get_doc(self, doc_id: str) -> dict | None:
        with self._lock:
            d = self._docs.get(doc_id)
            return dict(d.meta) if d else None

    def list_docs(self) -> list[dict]:
        with self._lock:
            metas = [dict(d.meta) for d in self._docs.values()]
        metas.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        return metas

    def delete_doc(self, doc_id: str) -> bool:
        with self._lock:
            d = self._docs.pop(doc_id, None)
        existed = d is not None
        try:
            (DOCS_DIR / f"{doc_id}.json").unlink(missing_ok=True)
        except OSError:
            pass
        if UPLOADS_DIR.exists() and re.fullmatch(r"[0-9a-f]{8}", doc_id):
            for p in UPLOADS_DIR.glob(f"{doc_id}*"):
                try:
                    p.unlink()
                except OSError:
                    pass
        return existed

    def doc_chunks(self, doc_id: str) -> list[Chunk]:
        """Shallow copy of the chunk list of a document (for summarisation)."""
        with self._lock:
            d = self._docs.get(doc_id)
            return list(d.chunks) if d else []

    # ---------------------------------------------------------------- search
    def search(self, query: str, doc_ids: list[str] | None = None, k: int = 8) -> list[Hit]:
        terms = list(dict.fromkeys(tokenize(query)))
        if not terms or k <= 0:
            return []
        with self._lock:
            if doc_ids:
                docs = [self._docs[i] for i in dict.fromkeys(doc_ids) if i in self._docs and self._docs[i].chunks]
            else:
                docs = [d for d in self._docs.values() if d.meta.get("status") == "ready" and d.chunks]
            if not docs:
                return []
            n_total = sum(len(d.chunks) for d in docs)
            if n_total == 0:
                return []
            avgdl = (sum(d.total_len for d in docs) / n_total) or 1.0

            idf: dict[str, float] = {}
            perfect = 0.0
            for t in terms:
                df = 0
                for d in docs:
                    arr = d.inv.get(t)
                    if arr is not None:
                        df += len(arr)
                v = math.log(1.0 + (n_total - df + 0.5) / (df + 0.5))
                idf[t] = v
                perfect += v * (K1 + 1.0)

            cand: list[tuple[float, int, int]] = []  # (score, doc_pos, chunk_idx)
            for pos, d in enumerate(docs):
                scores: dict[int, float] = {}
                lens = d.lens
                for t in terms:
                    arr = d.inv.get(t)
                    if arr is None:
                        continue
                    w = idf[t]
                    for packed in arr:
                        ci = packed >> 8
                        tf = packed & 255
                        norm_len = 1.0 - B + B * lens[ci] / avgdl
                        s = w * tf * (K1 + 1.0) / (tf + K1 * norm_len)
                        scores[ci] = scores.get(ci, 0.0) + s
                if scores:
                    for ci, s in heapq.nlargest(k, scores.items(), key=lambda kv: kv[1]):
                        cand.append((s, pos, ci))
            top = heapq.nlargest(k, cand, key=lambda x: x[0])
            hits = []
            for s, pos, ci in top:
                norm = s / perfect if perfect > 0 else 0.0
                norm = 0.0 if norm < 0 else 1.0 if norm > 1 else norm
                hits.append(Hit(chunk=docs[pos].chunks[ci], score=s, norm=norm))
            return hits

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        try:
            doc_id, n = chunk_id.rsplit("-", 1)
            n = int(n)
        except (ValueError, AttributeError):
            return None
        with self._lock:
            d = self._docs.get(doc_id)
            if d is None or not (0 <= n < len(d.chunks)):
                return None
            c = d.chunks[n]
            return c if c.id == chunk_id else None

    def stats(self) -> dict:
        with self._lock:
            docs = list(self._docs.values())
            return {
                "documents": len(docs),
                "pages": sum(int(d.meta.get("pages_total") or d.meta.get("pages_done") or 0) for d in docs),
                "chunks": sum(len(d.chunks) for d in docs),
                "words": sum(int(d.meta.get("words") or 0) for d in docs),
            }

    # ----------------------------------------------------------- persistence
    def _snapshot(self, d: _Doc) -> tuple[dict, list[Chunk]]:
        return dict(d.meta), list(d.chunks)

    def _write_snapshot(self, doc_id: str, snap: tuple[dict, list[Chunk]]) -> None:
        meta, chunks = snap
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        final = DOCS_DIR / f"{doc_id}.json"
        tmp = DOCS_DIR / f"{doc_id}.json.{uuid.uuid4().hex[:6]}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write('{"meta": ')
                json.dump(meta, f, ensure_ascii=False)
                f.write(', "chunks": [')
                first = True
                for c in chunks:
                    if not first:
                        f.write(",")
                    first = False
                    json.dump([c.page, c.heading, c.text, c.n_tokens], f, ensure_ascii=False)
                f.write("]}")
            # Do not resurrect a document deleted while we were writing.
            with self._lock:
                alive = doc_id in self._docs
            if alive:
                os.replace(tmp, final)
            else:
                tmp.unlink(missing_ok=True)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _load_all(self) -> None:
        for p in sorted(DOCS_DIR.glob("*.json")):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                meta = raw["meta"]
                doc_id = meta["id"]
            except Exception:
                continue
            d = _Doc(meta)
            self._docs[doc_id] = d
            filename = meta.get("filename", "")
            batch: list[Chunk] = []
            for n, (page, heading, text, n_tok) in enumerate(raw.get("chunks", [])):
                batch.append(Chunk(f"{doc_id}-{n}", doc_id, filename, page, heading, text, n_tok))
                if len(batch) >= 2000:
                    self.add_chunks(doc_id, batch)
                    batch = []
            self.add_chunks(doc_id, batch)
            del raw
            meta["chunks"] = len(d.chunks)
            if meta.get("status") not in TERMINAL:
                meta["status"] = "error"
                meta["error"] = "Interrupted by restart"
                self._write_snapshot(doc_id, self._snapshot(d))
        # Remove stale temp files from interrupted writes.
        for p in DOCS_DIR.glob("*.tmp"):
            try:
                p.unlink()
            except OSError:
                pass


store = Store()
