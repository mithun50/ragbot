# RagBot

Upload documents, then ask questions and get answers that cite the exact passages they came from. Answers are grounded: if the documents do not contain the answer, DocQA says so instead of guessing.

## Setup

Requires Python 3.10 or newer.

```
python -m venv .venv
.venv\Scripts\activate          # Windows (use source .venv/bin/activate on macOS or Linux)
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
OPENROUTER_API_KEY=your-key-here
OPENROUTER_MODEL=inclusionai/ling-3.2-flash:free
OPENROUTER_FALLBACK_MODELS=particle-ai/particle-1:free
```

The key is optional for trying things out: uploads, parsing, indexing and search work without it, but answers and AI summaries need it. The `.env` file is re-read on every request, so key and model changes apply without code changes.

## Run

```
uvicorn app.main:app --port 8000
```

Open http://localhost:8000.

## Environment variables

| Variable | Purpose |
| --- | --- |
| OPENROUTER_API_KEY | Your OpenRouter key. |
| OPENROUTER_MODEL | Primary model id (default inclusionai/ling-3.2-flash:free). |
| OPENROUTER_FALLBACK_MODELS | Comma separated models tried in order when the primary is rate limited, missing, or failing (default particle-ai/particle-1:free). |

## Architecture

```
static/            single page frontend (no build step)
app/main.py        FastAPI routes, streamed uploads, SSE framing
app/qa.py          ask(): rewrite, retrieve, gate, stream, cite
app/prompts.py     grounded QA system prompt, context formatting, rewrite prompt
app/llm.py         OpenRouter client with retries and fallbacks
app/analytics.py   question log (data/analytics.json) and summary
app/parsing.py     page iterators for PDF, DOCX and text formats
app/chunking.py    about 180 word overlapping chunks that never cross pages
app/index.py       thread safe store, hand written BM25 inverted index, persistence
app/summarize.py   map-reduce document summaries
app/ingest.py      background ingestion pipeline
data/              uploads, per-document JSON index files, analytics log
```

Question flow:

1. Follow-up questions are rewritten into standalone search queries using the chat history.
2. Query expansion: two extra local queries (key terms, and rare terms with quoted phrases and numbers boosted) are searched alongside the original, each with k=16, and merged by reciprocal rank fusion.
3. MMR (lambda 0.7, token Jaccard similarity) picks up to 7 distinct passages from the fused top 12.
4. Neighbour expansion appends the next same-page chunk to the top 2 passages so answers that span a chunk boundary still work, within the 6000 word context budget.
5. A relevance gate skips the model when the best passage for the original query scores below 0.12 and returns a not-found answer with the closest passages as hints.
6. Otherwise the passages are numbered, sent under a strict grounding prompt, and the answer is streamed over server-sent events, with stage updates (`status` events) along the way.
7. Citation markers like [1] are validated against the passages that were sent. A reply of NOT_FOUND is reported as not found.

An in-memory LRU cache (200 entries) replays answers for repeated stand-alone questions. Its key includes the document chunk counts, so re-uploading or deleting documents invalidates it. Errors are never cached.

The model client keeps one pooled keep-alive HTTP connection to OpenRouter, requests token usage in the stream, and falls back from the primary model to each fallback on rate limits, missing models, server errors or empty replies.

## HTTP API

- `GET /api/config` (llm_configured, model, models, app_name, version), `GET /api/health`
- `POST /api/documents` (multipart field `files`), `GET /api/documents`, `GET /api/documents/{id}`, `DELETE /api/documents/{id}`
- `POST /api/ask` streams `status`, `sources`, `token`, `done` (with a `metrics` object) and `error` events
- `GET /api/analytics`, `DELETE /api/analytics` (reset)

## How large documents are handled

- Uploads are streamed to disk in 1 MB blocks, up to 500 MB per file. Filenames are reduced to a safe basename.
- Ingestion runs in a background thread. PDF pages are read lazily one at a time and chunked as they arrive, so memory stays bounded no matter how many pages the file has. Progress (pages done of total) is visible live.
- Chunks are added to the index in batches of 200. Search uses an inverted index, so query time depends on the matching postings and not on the total number of chunks.
- Summaries of big documents are built map-reduce style from up to 12 evenly spaced samples rather than the whole text.
- Each document is persisted as JSON under `data/docs` and the index is rebuilt at startup. Documents interrupted by a restart are marked as errors and can be re-uploaded.

## Analytics notes

Questions whose model call failed are counted under `errors` and excluded from answered, not found, answer rate and latency averages. Time to first token (TTFT), p95 total time, cache hit rate, token totals and per-model timings are recorded per question. Per-document question counts attribute a question to the documents that supplied its retrieved passages. Average latency is retrieval time plus model time across all recorded questions.
