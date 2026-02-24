"""Semantic search against ChromaDB, with optional Claude summaries.

CLI usage:
    python retriever.py <query>
    python retriever.py copy_from_user
"""

from __future__ import annotations

import sys

import anthropic
import chromadb
from sentence_transformers import SentenceTransformer

from config import (
    ANTHROPIC_API_KEY,
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    MODEL_NAME,
)

_model: SentenceTransformer | None = None
_collection: chromadb.Collection | None = None
_client: anthropic.Anthropic | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        chroma = chromadb.PersistentClient(path=CHROMA_DIR)
        _collection = chroma.get_or_create_collection(COLLECTION_NAME)
    return _collection


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def search(query: str, limit: int = 5) -> list[dict]:
    """Return top-k matching function metadata dicts."""
    model = _get_model()
    collection = _get_collection()

    embedding = model.encode([query]).tolist()[0]
    results = collection.query(
        query_embeddings=[embedding],
        n_results=limit,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for i in range(len(results["ids"][0])):
        hits.append(
            {
                "id": results["ids"][0][i],
                "score": 1 - results["distances"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
            }
        )
    return hits


def summarize(query: str, hit: dict) -> str:
    """Ask Claude to summarize a search result in context of the query."""
    client = _get_client()
    prompt = (
        f"A developer searched for: \"{query}\"\n\n"
        f"The following Linux kernel function was retrieved:\n\n"
        f"{hit['document']}\n\n"
        f"File: {hit['metadata'].get('file_path', 'unknown')}\n\n"
        "Please provide a concise, developer-friendly summary of what this function does "
        "and why it is relevant to the search query."
    )
    message = client.messages.create(
        model=MODEL_NAME,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def search_with_summaries(query: str, limit: int = 5) -> list[dict]:
    """Search and attach a Claude summary to each result."""
    hits = search(query, limit=limit)
    for hit in hits:
        hit["summary"] = summarize(query, hit)
    return hits


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python retriever.py <query>")
        sys.exit(1)

    q = " ".join(sys.argv[1:])
    print(f"Searching for: {q}\n")
    hits = search(q, limit=5)
    for i, hit in enumerate(hits, 1):
        meta = hit["metadata"]
        print(f"--- Result {i} (score={hit['score']:.3f}) ---")
        print(f"Function : {meta.get('name')}")
        print(f"File     : {meta.get('file_path')}")
        print(f"Signature: {meta.get('signature')}")
        if meta.get("docstring"):
            print(f"Doc      : {meta['docstring']}")
        print()
        summary = summarize(q, hit)
        print(f"Summary  : {summary}\n")
