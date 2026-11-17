"""Retrieval evaluation for the Helios handbook through the real ingest pipeline.

Usage:  python tools/eval_retrieval.py [--k 8]

The document is ingested synchronously with app.ingest._pipeline (summarisation is stubbed
so no LLM is called). Index snapshots go to a temporary directory, and the document is
deleted from the store afterwards. Searches are scoped to the ingested document.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.index as index  # noqa: E402
from app import ingest, summarize  # noqa: E402

PDF = ROOT / "samples" / "helios_handbook.pdf"
QS = ROOT / "samples" / "helios_questions.json"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()
    k = args.k

    tmp = Path(tempfile.mkdtemp(prefix="docqa_eval_"))
    index.DOCS_DIR = tmp / "docs"
    index.UPLOADS_DIR = tmp / "uploads"
    index.DOCS_DIR.mkdir()
    index.UPLOADS_DIR.mkdir()
    summarize.summarize_document = lambda doc_id: {"summary": "", "key_facts": [], "suggested_questions": []}

    store = index.store
    meta = store.create_doc(PDF.name, PDF.stat().st_size)
    doc_id = meta["id"]
    t0 = time.perf_counter()
    ingest._pipeline(doc_id, PDF)
    ingest_s = time.perf_counter() - t0
    m = store.get_doc(doc_id)
    pages = m["pages_total"]
    chunks = store.doc_chunks(doc_id)
    print(f"ingest: {ingest_s:.2f}s, pages={pages}, {pages / ingest_s:.1f} pages/s, chunks={len(chunks)}, status={m['status']}")

    all_q = json.loads(QS.read_text(encoding="ascii"))
    answerable = [q for q in all_q if "expected_answer_contains" in q]
    oos = [q for q in all_q if q.get("expected") == "NOT_FOUND"]

    hits = {1: 0, 3: 0, min(k, 8): 0}
    lat = []
    failures = []
    for q in answerable:
        exp = norm(q["expected_answer_contains"])
        t = time.perf_counter()
        res = store.search(q["question"], doc_ids=[doc_id], k=k)
        lat.append((time.perf_counter() - t) * 1000)
        rank = None
        for i, h in enumerate(res, 1):
            if exp in norm(h.chunk.text) and h.chunk.page == q["page"]:
                rank = i
                break
        for kk in hits:
            if rank is not None and rank <= kk:
                hits[kk] += 1
        if rank is None or rank > 3:
            anywhere = [c.page for c in chunks if exp in norm(c.text)]
            if rank is None and not anywhere:
                why = "answer text is split across chunk boundaries or lost in parsing"
            elif rank is None:
                top_pages = [h.chunk.page for h in res]
                why = f"gold chunk not in top {k}; retrieved pages {top_pages}"
                if q.get("decoy_page") in top_pages:
                    why += " (decoy page was retrieved instead)"
            else:
                why = "gold chunk found but ranked below 3"
                if q.get("decoy_page") in [h.chunk.page for h in res[: rank - 1]]:
                    why += " (decoy ranked above it)"
            failures.append((q["id"], q["question"], q["page"], rank, why))

    n = len(answerable)
    print(f"questions: {n} answerable, {len(oos)} out of scope")
    for kk in sorted(hits):
        print(f"hit@{kk}: {hits[kk]}/{n} = {100 * hits[kk] / n:.1f}%")
    lat.sort()
    p95 = lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))]
    print(f"search latency ms: median={statistics.median(lat):.2f} p95={p95:.2f}")

    if failures:
        print("\nQuestions not hit@3:")
        for f in failures:
            print(f"  {f[0]} page {f[2]} rank={f[3]}: {f[1]}\n      {f[4]}")

    print("\nOut of scope questions (top score, normalised):")
    for q in oos:
        res = store.search(q["question"], doc_ids=[doc_id], k=1)
        top = f"{res[0].norm:.3f} (page {res[0].chunk.page})" if res else "no results"
        print(f"  {q['question']} -> {top}")
    if answerable:
        sc = []
        for q in answerable:
            r = store.search(q["question"], doc_ids=[doc_id], k=1)
            sc.append(r[0].norm if r else 0.0)
        print(f"  (answerable questions top norm score: min={min(sc):.3f} median={statistics.median(sc):.3f})")

    store.delete_doc(doc_id)
    print("\ncleaned up document", doc_id, "from the store; temp dir", tmp)


if __name__ == "__main__":
    main()
