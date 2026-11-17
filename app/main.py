"""RagBot FastAPI server: uploads, document management, streaming Q and A, analytics."""
from __future__ import annotations

import json
import os
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Iterator, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import analytics, ingest, llm, qa
from app.index import store

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
STATIC_DIR = ROOT / "static"

ALLOWED_EXT = {".pdf", ".docx", ".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm"}
MAX_BYTES = 500 * 1024 * 1024
CHUNK = 1024 * 1024

for _d in (DATA_DIR, UPLOAD_DIR, DATA_DIR / "docs", STATIC_DIR):
    _d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="RagBot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def _startup() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, DATA_DIR / "docs"):
        d.mkdir(parents=True, exist_ok=True)


def safe_filename(name: str) -> str:
    """Reduce an uploaded name to a safe basename: no paths, no odd characters, bounded length."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKC", name)
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^\w .\-]", "_", stem, flags=re.UNICODE).strip(" .")
    stem = re.sub(r"\s+", " ", stem)[:100] or "file"
    ext = re.sub(r"[^\w.]", "", ext).lower()[:10]
    return stem + ext


def _display_name(name: str) -> str:
    name = (name or "").replace("\\", "/").split("/")[-1].strip()
    return name or "file"


@app.get("/")
def index_page():
    page = STATIC_DIR / "index.html"
    if not page.exists():
        raise HTTPException(404, "Frontend not built yet: static/index.html is missing.")
    return FileResponse(str(page), headers={"Cache-Control": "no-cache"})


@app.get("/api/config")
def config():
    return {
        "llm_configured": llm.is_configured(),
        "model": llm.current_model(),
        "models": llm.models(),
        "app_name": "RagBot",
        "version": "1.0",
    }


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/documents")
def upload_documents(files: list[UploadFile] = File(...)):
    # Validate every file before touching disk so a bad batch saves nothing.
    for f in files:
        shown = _display_name(f.filename)
        if os.path.splitext(shown)[1].lower() not in ALLOWED_EXT:
            raise HTTPException(
                400,
                f"Unsupported file type: {shown}. Allowed types: PDF, DOCX, TXT, MD, CSV, JSON, HTML.",
            )
    results = []
    for f in files:
        shown = _display_name(f.filename)
        safe = safe_filename(shown)
        tmp = UPLOAD_DIR / f".incoming_{uuid.uuid4().hex}"
        size = 0
        try:
            with open(tmp, "wb") as out:
                while True:
                    block = f.file.read(CHUNK)
                    if not block:
                        break
                    size += len(block)
                    if size > MAX_BYTES:
                        raise HTTPException(413, f"{shown} is larger than the 500 MB limit.")
                    out.write(block)
            if size == 0:
                raise HTTPException(400, f"{shown} is empty.")
            meta = store.create_doc(shown, size)
            dest = UPLOAD_DIR / f"{meta['id']}_{safe}"
            os.replace(tmp, dest)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        ingest.start_ingest(meta["id"], dest)
        results.append(store.get_doc(meta["id"]) or meta)
    return {"documents": results}


@app.get("/api/documents")
def list_documents():
    return {"documents": store.list_docs()}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    doc = store.get_doc(doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    if store.get_doc(doc_id) is None:
        raise HTTPException(404, "Document not found")
    store.delete_doc(doc_id)
    return {"ok": True}


class HistoryItem(BaseModel):
    role: str
    content: str


class AskBody(BaseModel):
    question: str
    doc_ids: Optional[list[str]] = None
    history: Optional[list[HistoryItem]] = None


def _frames(body: AskBody) -> Iterator[str]:
    history = [h.model_dump() for h in (body.history or [])]
    try:
        for ev in qa.ask(body.question, body.doc_ids or [], history):
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"
    except Exception:
        err = {"message": "Something went wrong while answering. Please try again."}
        yield f"event: error\ndata: {json.dumps(err)}\n\n"


@app.post("/api/ask")
def ask(body: AskBody):
    return StreamingResponse(
        _frames(body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.get("/api/analytics")
def get_analytics():
    return analytics.summary()


@app.delete("/api/analytics")
def reset_analytics():
    analytics.reset()
    return {"ok": True}
