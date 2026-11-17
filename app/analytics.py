"""Thread-safe question log persisted to data/analytics.json, plus the summary view."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_PATH = DATA_DIR / "analytics.json"
MAX_RECORDS = 20000

_lock = threading.Lock()
_records: list[dict] = []
_loaded = False


def _load() -> None:
    global _loaded, _records
    if _loaded:
        return
    _loaded = True
    try:
        data = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            _records = [r for r in data if isinstance(r, dict)]
    except (OSError, ValueError):
        _records = []


def _save() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = LOG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_records), encoding="utf-8")
        os.replace(tmp, LOG_PATH)
    except OSError:
        pass


def record(question, found, retrieval_ms, llm_ms, top_score, doc_ids, n_citations, n_sources,
           metrics=None, error=False) -> None:
    m = metrics or {}
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "question": str(question or "")[:500],
        "found": bool(found),
        "retrieval_ms": int(retrieval_ms or 0),
        "llm_ms": int(llm_ms or 0),
        "top_score": round(float(top_score or 0.0), 4),
        "doc_ids": list(doc_ids or []),
        "n_citations": int(n_citations or 0),
        "n_sources": int(n_sources or 0),
        "error": bool(error),
        "ttft_ms": int(m.get("ttft_ms") or 0),
        "total_ms": int(m.get("total_ms") or 0) or int(retrieval_ms or 0) + int(llm_ms or 0),
        "cached": bool(m.get("cache_hit")),
        "prompt_tokens": int(m.get("prompt_tokens") or 0),
        "completion_tokens": int(m.get("completion_tokens") or 0),
        "cached_tokens": int(m.get("cached_tokens") or 0),
        "tokens_per_sec": float(m.get("tokens_per_sec") or 0.0),
        "model": str(m.get("model") or ""),
    }
    with _lock:
        _load()
        _records.append(rec)
        if len(_records) > MAX_RECORDS:
            del _records[: len(_records) - MAX_RECORDS]
        _save()


def _bucket_index(score: float) -> int:
    return max(0, min(4, int(score * 5)))


def reset() -> None:
    with _lock:
        _load()
        _records.clear()
        _save()


def _avg(vals) -> int:
    vals = list(vals)
    return int(sum(vals) / len(vals)) if vals else 0


def _p95(vals) -> int:
    vals = sorted(vals)
    if not vals:
        return 0
    return int(vals[min(len(vals) - 1, int(0.95 * len(vals) + 0.999999) - 1)])


def summary() -> dict:
    from app.index import store

    with _lock:
        _load()
        recs = list(_records)

    stats = store.stats()
    n = len(recs)
    ok = [r for r in recs if not r.get("error")]
    errors = n - len(ok)
    answered = sum(1 for r in ok if r["found"])
    not_found = len(ok) - answered
    k = len(ok)

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    hours = [now - timedelta(hours=i) for i in range(23, -1, -1)]
    counts = {h: 0 for h in hours}
    for r in recs:
        try:
            ts = datetime.fromisoformat(r["ts"]).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        except (ValueError, KeyError):
            continue
        if ts in counts:
            counts[ts] += 1
    timeline = [{"t": h.isoformat().replace("+00:00", "Z"), "count": counts[h]} for h in hours]

    labels = ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
    buckets = [0] * 5
    for r in ok:
        buckets[_bucket_index(float(r.get("top_score", 0.0)))] += 1

    per_doc_q: dict[str, int] = {}
    for r in ok:
        for d in set(r.get("doc_ids") or []):
            per_doc_q[d] = per_doc_q.get(d, 0) + 1
    per_document = []
    for d in store.list_docs():
        per_document.append({
            "doc_id": d["id"],
            "filename": d["filename"],
            "questions": per_doc_q.get(d["id"], 0),
            "pages": int(d.get("pages_total") or 0),
            "chunks": int(d.get("chunks") or 0),
        })
    per_document.sort(key=lambda x: x["questions"], reverse=True)

    recent = [
        {
            "question": r["question"],
            "found": r["found"],
            "latency_ms": r["retrieval_ms"] + r["llm_ms"],
            "top_score": r["top_score"],
            "ts": r["ts"],
            "ttft_ms": r.get("ttft_ms", 0),
            "total_ms": r.get("total_ms", 0),
            "cached": r.get("cached", False),
            "prompt_tokens": r.get("prompt_tokens", 0),
            "completion_tokens": r.get("completion_tokens", 0),
            "model": r.get("model", ""),
            "error": r.get("error", False),
        }
        for r in reversed(recs[-12:])
    ]

    by_model: dict[str, list[dict]] = {}
    for r in ok:
        if r.get("model") and not r.get("cached"):
            by_model.setdefault(r["model"], []).append(r)
    by_model_out = [
        {
            "model": mname,
            "count": len(rs),
            "avg_ttft_ms": _avg(x.get("ttft_ms", 0) for x in rs),
            "avg_total_ms": _avg(x.get("total_ms", 0) for x in rs),
        }
        for mname, rs in sorted(by_model.items(), key=lambda kv: -len(kv[1]))
    ]
    speeds = [r["tokens_per_sec"] for r in ok if r.get("tokens_per_sec")]

    return {
        "totals": {
            "documents": stats.get("documents", 0),
            "pages": stats.get("pages", 0),
            "chunks": stats.get("chunks", 0),
            "words": stats.get("words", 0),
            "questions": n,
        },
        "answered": answered,
        "not_found": not_found,
        "errors": errors,
        "answer_rate": round(answered / k, 4) if k else 0.0,
        "avg_latency_ms": _avg(r["retrieval_ms"] + r["llm_ms"] for r in ok),
        "avg_retrieval_ms": _avg(r["retrieval_ms"] for r in ok),
        "avg_citations": round(sum(r["n_citations"] for r in ok) / k, 2) if k else 0.0,
        "avg_ttft_ms": _avg(r.get("ttft_ms", 0) for r in ok),
        "p95_total_ms": _p95([r.get("total_ms", 0) for r in ok]),
        "cache_hit_rate": round(sum(1 for r in ok if r.get("cached")) / k, 4) if k else 0.0,
        "total_prompt_tokens": sum(r.get("prompt_tokens", 0) for r in ok),
        "total_completion_tokens": sum(r.get("completion_tokens", 0) for r in ok),
        "total_cached_tokens": sum(r.get("cached_tokens", 0) for r in ok),
        "avg_tokens_per_sec": round(sum(speeds) / len(speeds), 1) if speeds else 0.0,
        "by_model": by_model_out,
        "per_document": per_document,
        "timeline": timeline,
        "score_buckets": [{"label": labels[i], "count": buckets[i]} for i in range(5)],
        "recent": recent,
    }
