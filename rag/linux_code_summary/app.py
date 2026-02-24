"""FastAPI server for Linux kernel code search.

Endpoints:
    POST /search   — semantic search, optionally with Claude summaries
    GET  /stats    — collection stats
    POST /sync     — trigger incremental git sync
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

import chromadb
from sentence_transformers import SentenceTransformer

from config import CHROMA_DIR, COLLECTION_NAME, EMBEDDING_MODEL
from retriever import search, search_with_summaries
from sync import sync


# --- Startup / shutdown ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up the embedding model on startup
    SentenceTransformer(EMBEDDING_MODEL)
    yield


app = FastAPI(
    title="Linux Kernel Code Search",
    description="RAG-powered semantic search over Linux kernel functions",
    version="1.0.0",
    lifespan=lifespan,
)


# --- Request / response schemas ---

class SearchRequest(BaseModel):
    query: str
    limit: int = 5
    summaries: bool = False


class SearchResult(BaseModel):
    name: str
    file_path: str
    signature: str
    docstring: str
    score: float
    summary: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


# --- Routes ---

@app.get("/")
def root():
    return RedirectResponse(url="/docs")


@app.post("/search", response_model=SearchResponse)
def search_endpoint(req: SearchRequest) -> SearchResponse:
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    if req.summaries:
        hits = search_with_summaries(req.query, limit=req.limit)
    else:
        hits = search(req.query, limit=req.limit)

    results = [
        SearchResult(
            name=h["metadata"].get("name", ""),
            file_path=h["metadata"].get("file_path", ""),
            signature=h["metadata"].get("signature", ""),
            docstring=h["metadata"].get("docstring", ""),
            score=round(h["score"], 4),
            summary=h.get("summary"),
        )
        for h in hits
    ]
    return SearchResponse(query=req.query, results=results)


@app.get("/stats")
def stats_endpoint() -> dict:
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_or_create_collection(COLLECTION_NAME)
    return {
        "collection": COLLECTION_NAME,
        "total_functions": collection.count(),
    }


class SyncRequest(BaseModel):
    kernel_path: str = ""


@app.post("/sync")
def sync_endpoint(req: SyncRequest = SyncRequest()) -> dict:
    try:
        from config import KERNEL_PATH
        path = req.kernel_path or KERNEL_PATH
        return sync(kernel_path=path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
