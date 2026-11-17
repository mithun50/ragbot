"""Ingestion pipeline: parse -> chunk -> index -> summarise, in a daemon thread."""

from __future__ import annotations

import threading
from pathlib import Path

from app import parsing, summarize
from app.chunking import chunk_pages
from app.index import store

BATCH = 200
UPDATE_EVERY_PAGES = 10

# Bound concurrent ingests so several huge uploads cannot exhaust memory.
_slots = threading.BoundedSemaphore(2)


def _run(doc_id: str, path: Path) -> None:
    with _slots:
        try:
            _pipeline(doc_id, path)
        except parsing.ParseError as e:
            store.update_doc(doc_id, status="error", error=e.message)
        except MemoryError:
            store.update_doc(doc_id, status="error", error="The file is too large to process with the available memory.")
        except Exception as e:
            msg = str(e).strip() or type(e).__name__
            store.update_doc(doc_id, status="error", error=f"Could not process this file: {msg[:200]}")


def _pipeline(doc_id: str, path: Path) -> None:
    meta = store.get_doc(doc_id)
    if meta is None:
        return
    filename = meta["filename"]
    store.update_doc(doc_id, status="parsing", pages_done=0)

    total = parsing.count_pages(path, filename)
    if total:
        store.update_doc(doc_id, pages_total=total)

    state = {"pages": 0, "last_page": 0, "words": 0, "since_update": 0}

    def counted_pages():
        for page_no, text in parsing.iter_pages(path, filename):
            state["pages"] += 1
            state["last_page"] = page_no
            state["words"] += len(text.split())
            state["since_update"] += 1
            yield page_no, text

    batch = []
    n_chunks = 0
    last_pushed_chunks = 0
    last_pushed_pages = 0
    for chunk in chunk_pages(counted_pages(), doc_id, filename):
        if store.get_doc(doc_id) is None:
            return  # deleted while processing
        batch.append(chunk)
        n_chunks += 1
        if len(batch) >= BATCH:
            store.add_chunks(doc_id, batch)
            batch = []
        if (
            n_chunks - last_pushed_chunks >= BATCH
            or state["pages"] - last_pushed_pages >= UPDATE_EVERY_PAGES
        ):
            store.update_doc(
                doc_id,
                pages_done=state["last_page"] if total else state["pages"],
                chunks=n_chunks,
                words=state["words"],
            )
            last_pushed_chunks = n_chunks
            last_pushed_pages = state["pages"]
    if batch:
        store.add_chunks(doc_id, batch)
        batch = []

    if n_chunks == 0:
        raise parsing.ParseError("No text could be extracted from this file. It may be scanned or empty.")

    pages_final = total or state["pages"]
    store.update_doc(
        doc_id,
        status="indexing",
        pages_total=pages_final,
        pages_done=pages_final,
        chunks=n_chunks,
        words=state["words"],
    )
    store.finalize(doc_id)

    # Searchable immediately; the summary is filled in afterwards so questions never wait on it.
    store.update_doc(doc_id, status="ready")
    result = summarize.summarize_document(doc_id)
    if store.get_doc(doc_id) is not None:
        store.update_doc(
            doc_id,
            summary=result.get("summary", ""),
            key_facts=result.get("key_facts", []),
            suggested_questions=result.get("suggested_questions", []),
        )


def start_ingest(doc_id: str, path: Path) -> None:
    t = threading.Thread(target=_run, args=(doc_id, Path(path)), name=f"ingest-{doc_id}", daemon=True)
    t.start()
