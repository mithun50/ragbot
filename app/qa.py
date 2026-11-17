"""Question answering pipeline: expand, retrieve, fuse, diversify, stream a grounded answer, cite."""
from __future__ import annotations

import dataclasses
import re
import threading
import time
from collections import OrderedDict
from typing import Iterator

from app import analytics, llm, prompts
from app.index import Hit, store, tokenize

MIN_NORM = 0.12
SEARCH_K = 16
FUSED_POOL = 12
FINAL_K = 7
RRF_K = 60
MMR_LAMBDA = 0.7
CONTEXT_WORD_BUDGET = 3600
NEIGHBOUR_OVERLAP_WORDS = 30
MAX_QUESTION_CHARS = 4000
HISTORY_TURNS = 6
CACHE_SIZE = 200
NOT_FOUND = "NOT_FOUND"
_CITE_RE = re.compile(r"\[(\d{1,3})\]")

_QUESTION_WORDS = {
    "what", "whats", "which", "who", "whom", "whose", "when", "where", "why", "how", "is", "are", "was",
    "were", "do", "does", "did", "can", "could", "should", "would", "will", "shall", "may", "might",
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "from", "by", "with", "about", "and", "or",
    "me", "tell", "explain", "describe", "give", "show", "list", "please", "there", "this", "that",
    "these", "those", "it", "its", "be", "been", "being", "have", "has", "had", "i", "you", "we",
    "document", "documents", "text", "mentioned", "according",
}
_QUOTED_RE = re.compile(r"\"([^\"]{2,80})\"|'([^']{3,80})'")
_NUMBER_RE = re.compile(r"\b\d[\d,.\-/%]*\b")

_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_cache_lock = threading.Lock()


def _ev(event: str, **data) -> dict:
    return {"event": event, "data": data}


def _source(n: int, hit) -> dict:
    c = hit.chunk
    return {
        "n": n,
        "doc_id": c.doc_id,
        "filename": c.filename,
        "page": c.page,
        "heading": c.heading,
        "text": c.text,
        "score": round(float(hit.norm), 4),
    }


def _clean_history(history) -> list[dict]:
    out = []
    for m in history or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = str(m.get("content") or "").strip()
        if role in ("user", "assistant") and content and content != NOT_FOUND:
            out.append({"role": role, "content": content[:1200]})
    return out[-HISTORY_TURNS:]


def _rewrite(question: str, history: list[dict]) -> str:
    if not history or not llm.is_configured():
        return question
    convo = "\n".join(f"{m['role'].upper()}: {m['content'][:400]}" for m in history)
    messages = [
        {"role": "system", "content": prompts.REWRITE_PROMPT},
        {"role": "user", "content": f"CONVERSATION:\n{convo}\n\nLATEST QUESTION: {question}\n\nStandalone query:"},
    ]
    try:
        text = llm.complete(messages, max_tokens=80, temperature=0.0)
    except Exception:
        return question
    text = text.strip().splitlines()[0].strip().strip('"').strip() if text.strip() else ""
    return text if 2 <= len(text) <= 400 else question


# ---------------------------------------------------------------- query expansion

def expand_queries(question: str) -> list[str]:
    """Return up to 2 extra cheap local queries: key terms, and a rare-term focused variant."""
    quoted = [a or b for a, b in _QUOTED_RE.findall(question)]
    numbers = _NUMBER_RE.findall(question)
    boost = " ".join(quoted + numbers)
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", question)
    keys = [w for w in words if w.lower().strip("'") not in _QUESTION_WORDS]
    out: list[str] = []
    if keys:
        out.append(" ".join(keys + ([boost, boost] if boost else [])))
    long_terms = sorted(set(w for w in keys if len(w) >= 6 or w[:1].isupper()), key=len, reverse=True)[:5]
    if long_terms:
        out.append(" ".join(long_terms + ([boost] if boost else [])))
    uniq: list[str] = []
    for q in out:
        q = q.strip()
        if q and q != question and q not in uniq:
            uniq.append(q)
    return uniq[:2]


# ---------------------------------------------------------------- fusion and diversification

def rrf_fuse(rankings: list[list[Hit]]) -> list[tuple[Hit, float]]:
    """Reciprocal rank fusion. The first ranking's hit object wins so its norm is the primary score."""
    scores: dict[str, float] = {}
    best: dict[str, Hit] = {}
    for ranking in rankings:
        for rank, h in enumerate(ranking):
            cid = h.chunk.id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
            best.setdefault(cid, h)
    order = sorted(scores, key=lambda c: scores[c], reverse=True)
    return [(best[c], scores[c]) for c in order]


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def mmr_select(cands: list[tuple[Hit, float]], k: int = FINAL_K, lam: float = MMR_LAMBDA) -> list[Hit]:
    if not cands:
        return []
    top = cands[0][1] or 1.0
    sets = [set(tokenize(h.chunk.text)) for h, _ in cands]
    rel = [s / top for _, s in cands]
    chosen = [0]
    rest = list(range(1, len(cands)))
    while rest and len(chosen) < k:
        def val(i):
            return lam * rel[i] - (1 - lam) * max(_jaccard(sets[i], sets[j]) for j in chosen)
        nxt = max(rest, key=val)
        rest.remove(nxt)
        chosen.append(nxt)
    return [cands[i][0] for i in chosen]


def _split_id(cid: str):
    base, _, n = cid.rpartition("-")
    return (base, int(n)) if base and n.isdigit() else (None, None)


def expand_neighbours(hits: list[Hit], budget: int = CONTEXT_WORD_BUDGET, top_n: int = 4) -> list[Hit]:
    """Append the following same-page chunk to the top passages (copies, the store is never mutated)."""
    used = sum(len(h.chunk.text.split()) for h in hits)
    present = {h.chunk.id for h in hits}
    out = list(hits)
    for idx in range(min(top_n, len(out))):
        c = out[idx].chunk
        base, n = _split_id(c.id)
        if base is None:
            continue
        nid = f"{base}-{n + 1}"
        if nid in present:
            continue
        nxt = store.get_chunk(nid)
        if nxt is None or nxt.doc_id != c.doc_id or nxt.page != c.page:
            continue
        extra = " ".join(nxt.text.split()[NEIGHBOUR_OVERLAP_WORDS:])
        w = len(extra.split())
        if not extra or used + w > budget:
            continue
        used += w
        out[idx] = dataclasses.replace(out[idx], chunk=dataclasses.replace(c, text=c.text.rstrip() + " " + extra))
    return out


def _select_for_budget(hits: list[Hit]) -> list[Hit]:
    chosen, words = [], 0
    for h in hits:
        w = len(h.chunk.text.split())
        if chosen and words + w > CONTEXT_WORD_BUDGET:
            break
        chosen.append(h)
        words += w
    return chosen


# ---------------------------------------------------------------- cache

def _norm_q(q: str) -> str:
    return " ".join(re.findall(r"\w+", q.lower()))


def _cache_key(question: str, scope, ready_ids, model=None) -> tuple:
    ids = sorted(scope or ready_ids)
    fp = []
    for i in ids:
        d = store.get_doc(i) or {}
        fp.append((i, d.get("chunks", 0), d.get("words", 0)))
    return (_norm_q(question), tuple(fp), model or "")


def _cache_get(key):
    with _cache_lock:
        v = _cache.get(key)
        if v is not None:
            _cache.move_to_end(key)
        return v


def _cache_put(key, value) -> None:
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _citations(text: str, n_sources: int) -> list[int]:
    return sorted({int(m) for m in _CITE_RE.findall(text) if 1 <= int(m) <= n_sources})


def _could_be_not_found(buf: str) -> bool:
    s = buf.lstrip()
    return NOT_FOUND.startswith(s) or s.startswith(NOT_FOUND)  # empty s matches too


# ---------------------------------------------------------------- pipeline

OVERVIEW_PASSAGES = 8
WEAK_NORM = 0.35


def _sample_hits(doc_ids) -> list[Hit]:
    """Broad questions match no single passage, so sample the opening and evenly spaced passages of each document."""
    ids = list(doc_ids)
    per_doc = max(3, OVERVIEW_PASSAGES // max(1, len(ids)))
    out: list[Hit] = []
    for did in ids:
        chunks = store.doc_chunks(did) or []
        if not chunks:
            continue
        picks = {0, 1}
        step = max(1, len(chunks) // per_doc)
        picks.update(range(0, len(chunks), step))
        for i in sorted(p for p in picks if p < len(chunks))[:per_doc]:
            out.append(Hit(chunk=chunks[i], score=0.5, norm=0.5))
    return out[:OVERVIEW_PASSAGES]


def ask(question: str, doc_ids, history, model=None) -> Iterator[dict]:
    t_start = time.perf_counter()

    def elapsed() -> int:
        return int((time.perf_counter() - t_start) * 1000)

    def status(stage: str, label: str, **extra) -> dict:
        return _ev("status", stage=stage, label=label, elapsed_ms=elapsed(), **extra)

    question = (question or "").strip()
    if not question:
        yield _ev("error", message="Please type a question.")
        return
    question = question[:MAX_QUESTION_CHARS]

    ready = {d["id"] for d in store.list_docs() if d.get("status") == "ready"}
    if not ready:
        yield _ev("error", message="Upload a document first")
        return
    selected = [d for d in (doc_ids or []) if isinstance(d, str)]
    if selected:
        scope = [d for d in selected if d in ready]
        if not scope:
            yield _ev("error", message="The selected documents are not ready yet. Wait for processing to finish or select other documents.")
            return
    else:
        scope = None

    hist = _clean_history(history)

    # Answer cache, only for stand-alone questions.
    ckey = _cache_key(question, scope, ready, model) if not hist else None
    if ckey is not None:
        hit = _cache_get(ckey)
        if hit is not None:
            yield _ev("sources", sources=hit["sources"])
            ttft = max(1, elapsed())
            if hit["found"]:
                yield _ev("token", text=hit["answer"])
            total = max(ttft, elapsed())
            m = dict(hit["metrics"], ttft_ms=ttft, total_ms=total, retrieval_ms=0, llm_ms=0,
                     cache_hit=True, tokens_per_sec=0.0, prompt_tokens=0, completion_tokens=0, cached_tokens=0)
            try:
                analytics.record(question, hit["found"], 0, 0, hit["top"],
                                 hit["doc_ids"], len(hit["citations"]), len(hit["sources"]), metrics=m)
            except Exception:
                pass
            yield _ev("done", answer=hit["answer"], found=hit["found"], citations=hit["citations"],
                      latency_ms={"retrieval": 0, "llm": 0}, top_score=hit["top"], metrics=m)
            return

    yield status("retrieving", "Searching your documents")
    t0 = time.perf_counter()
    query = _rewrite(question, hist)
    try:
        primary = store.search(query, scope, k=SEARCH_K)
        rankings = [primary]
        for q in expand_queries(query):
            rankings.append(store.search(q, scope, k=SEARCH_K))
    except Exception:
        yield _ev("error", message="Search failed unexpectedly. Please try again.")
        return
    fused = rrf_fuse(rankings)
    yield status("ranking", "Ranking passages", candidates=len(fused))
    top = float(primary[0].norm) if primary else 0.0
    selected_hits = mmr_select(fused[:FUSED_POOL]) if primary else []
    selected_hits = expand_neighbours(selected_hits) if selected_hits else []
    if not primary or top < WEAK_NORM:
        # Weak or no keyword match (broad or conversational question): add document-wide context rather than refusing.
        sampled = _sample_hits(scope or ready)
        if sampled:
            seen = {h.chunk.id for h in selected_hits}
            selected_hits = (selected_hits + [h for h in sampled if h.chunk.id not in seen])[:OVERVIEW_PASSAGES]
            primary, top = primary or sampled, max(top, 0.5)
    retrieval_ms = int((time.perf_counter() - t0) * 1000)

    def metrics(**kw) -> dict:
        m = {"ttft_ms": 0, "total_ms": 0, "retrieval_ms": retrieval_ms, "llm_ms": 0, "prompt_tokens": 0,
             "completion_tokens": 0, "cached_tokens": 0, "tokens_per_sec": 0.0, "cache_hit": False,
             "model": "", "passages": 0, "estimated_tokens": False}
        m.update(kw)
        return m

    def log(found, llm_ms, used_hits, n_cit, m, error=False):
        try:
            analytics.record(
                question, found, retrieval_ms, llm_ms, top,
                list(dict.fromkeys(h.chunk.doc_id for h in used_hits)), n_cit, len(used_hits),
                metrics=m, error=error,
            )
        except Exception:
            pass

    # Gate: weak retrieval means skip the LLM entirely.
    if not primary or top < MIN_NORM:
        hints = primary[:3]
        srcs = [_source(i, h) for i, h in enumerate(hints, 1)]
        yield _ev("sources", sources=srcs)
        total = elapsed()
        m = metrics(ttft_ms=total, total_ms=total, passages=len(hints))
        log(False, 0, hints, 0, m)
        if ckey is not None:
            _cache_put(ckey, {"sources": srcs, "answer": NOT_FOUND, "found": False, "citations": [], "top": round(top, 4),
                              "metrics": m, "doc_ids": list(dict.fromkeys(h.chunk.doc_id for h in hints))})
        yield _ev("done", answer=NOT_FOUND, found=False, citations=[],
                  latency_ms={"retrieval": retrieval_ms, "llm": 0}, top_score=round(top, 4), metrics=m)
        return

    used = _select_for_budget(selected_hits)
    yield status("reading", f"Reading {len(used)} passages", passages=len(used))
    srcs = [_source(i, h) for i, h in enumerate(used, 1)]
    yield _ev("sources", sources=srcs)

    if not llm.is_configured():
        log(False, 0, used, 0, metrics(total_ms=elapsed(), passages=len(used)), error=True)
        yield _ev("error", message="Add OPENROUTER_API_KEY to .env to enable answers")
        return

    messages = [{"role": "system", "content": prompts.SYSTEM_PROMPT}]
    messages.extend(hist[-4:])
    messages.append({"role": "user", "content": prompts.build_user_message(question, prompts.build_context(used))})

    yield status("generating", "Writing the answer")
    t1 = time.perf_counter()
    acc = ""
    pending = ""      # held back while the text could still turn out to be NOT_FOUND
    holding = True
    thinking_sent = False
    ttft = None
    usage = None
    try:
        for ev in llm.stream_events(messages, max_tokens=1500, temperature=0.1, model=model):
            kind = ev.get("type")
            if kind == "thinking":
                if not thinking_sent:
                    thinking_sent = True
                    yield status("thinking", "Thinking")
            elif kind == "usage":
                usage = ev
            elif kind == "token":
                piece = ev["text"]
                if ttft is None:
                    ttft = elapsed()
                acc += piece
                if holding:
                    pending += piece
                    if _could_be_not_found(pending):
                        continue
                    holding = False
                    yield _ev("token", text=pending)
                    pending = ""
                else:
                    yield _ev("token", text=piece)
    except llm.LLMNotConfigured:
        log(False, 0, used, 0, metrics(total_ms=elapsed(), passages=len(used)), error=True)
        yield _ev("error", message="Add OPENROUTER_API_KEY to .env to enable answers")
        return
    except llm.LLMError as e:
        log(False, int((time.perf_counter() - t1) * 1000), used, 0, metrics(total_ms=elapsed(), passages=len(used)), error=True)
        yield _ev("error", message=e.message)
        return
    except Exception:
        log(False, int((time.perf_counter() - t1) * 1000), used, 0, metrics(total_ms=elapsed(), passages=len(used)), error=True)
        yield _ev("error", message="Something went wrong while generating the answer. Please try again.")
        return
    llm_s = time.perf_counter() - t1
    llm_ms = int(llm_s * 1000)
    total = elapsed()

    final = acc.strip()
    found = not final.startswith(NOT_FOUND)
    if usage:
        pt, ct, cached = usage["prompt_tokens"], usage["completion_tokens"], usage.get("cached_tokens", 0)
        est, model = bool(usage.get("estimated")), usage.get("model") or llm.current_model()
    else:
        pt = int(sum(len(str(m.get("content", "")).split()) for m in messages) * 1.3)
        ct, cached, est, model = int(len(final.split()) * 1.3), 0, True, llm.current_model()
    m = metrics(ttft_ms=ttft if ttft is not None else total, total_ms=total, llm_ms=llm_ms,
                prompt_tokens=pt, completion_tokens=ct, cached_tokens=cached,
                tokens_per_sec=round(ct / llm_s, 1) if llm_s > 0 else 0.0,
                model=model, passages=len(used), estimated_tokens=est)

    if not found:
        log(False, llm_ms, used, 0, m)
        if ckey is not None:
            _cache_put(ckey, {"sources": srcs, "answer": NOT_FOUND, "found": False, "citations": [], "top": round(top, 4),
                              "metrics": m, "doc_ids": list(dict.fromkeys(h.chunk.doc_id for h in used))})
        yield _ev("done", answer=NOT_FOUND, found=False, citations=[],
                  latency_ms={"retrieval": retrieval_ms, "llm": llm_ms}, top_score=round(top, 4), metrics=m)
        return

    if holding and pending:
        yield _ev("token", text=pending)
    cites = _citations(final, len(used))
    log(True, llm_ms, used, len(cites), m)
    if ckey is not None:
        _cache_put(ckey, {"sources": srcs, "answer": final, "found": True, "citations": cites, "top": round(top, 4),
                          "metrics": m, "doc_ids": list(dict.fromkeys(h.chunk.doc_id for h in used))})
    yield _ev("done", answer=final, found=True, citations=cites,
              latency_ms={"retrieval": retrieval_ms, "llm": llm_ms}, top_score=round(top, 4), metrics=m)
