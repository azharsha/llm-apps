"""Embed kernel functions and upsert into ChromaDB.

Usage:
    python indexer.py --full                       # re-index all configured subsystems
    python indexer.py --files kernel/sched/core.c  # incremental update for specific files
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from config import (
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    KERNEL_PATH,
    SUBSYSTEMS,
)
from parser import parse_file


def _func_id(func: dict, idx: int = 0) -> str:
    """Stable document ID: sha1 of file_path + function name + occurrence index."""
    raw = f"{func['file_path']}::{func['name']}::{idx}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _func_document(func: dict) -> str:
    """Text representation fed to the embedding model."""
    parts = [f"Function: {func['name']}", f"Signature: {func['signature']}"]
    if func["docstring"]:
        parts.append(f"Doc: {func['docstring']}")
    parts.append(func["body_snippet"])
    return "\n".join(parts)


def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    return client.get_or_create_collection(COLLECTION_NAME)


def index_files(filepaths: list[str], collection: chromadb.Collection, model: SentenceTransformer) -> int:
    """Parse, embed, and upsert functions from the given C files. Returns count indexed."""
    all_funcs = []
    for fp in filepaths:
        all_funcs.extend(parse_file(fp))

    if not all_funcs:
        return 0

    documents = [_func_document(f) for f in all_funcs]
    embeddings = model.encode(documents, show_progress_bar=False).tolist()
    # Use per-occurrence index to handle duplicate function names in the same file
    name_counts: dict[str, int] = {}
    ids = []
    for f in all_funcs:
        key = f"{f['file_path']}::{f['name']}"
        idx = name_counts.get(key, 0)
        ids.append(_func_id(f, idx))
        name_counts[key] = idx + 1
    metadatas = [
        {
            "name": f["name"],
            "file_path": f["file_path"],
            "signature": f["signature"],
            "docstring": f["docstring"][:500],
        }
        for f in all_funcs
    ]

    batch_size = 500
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i : i + batch_size],
            documents=documents[i : i + batch_size],
            embeddings=embeddings[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
        )

    return len(all_funcs)


def collect_c_files(base: str, subsystems: list[str]) -> list[str]:
    files = []
    for sub in subsystems:
        subpath = Path(base) / sub
        if subpath.exists():
            files.extend(str(p) for p in subpath.rglob("*.c"))
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Index Linux kernel functions into ChromaDB")
    parser.add_argument(
        "--kernel-path",
        default=KERNEL_PATH,
        metavar="PATH",
        help="Path to the kernel source tree (overrides KERNEL_PATH env var)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full", action="store_true", help="Re-index all configured subsystems")
    group.add_argument("--files", nargs="+", metavar="FILE", help="Re-index specific C files")
    args = parser.parse_args()

    if args.full and not args.kernel_path:
        parser.error("--kernel-path (or KERNEL_PATH env var) is required for --full indexing")

    print(f"Loading embedding model '{EMBEDDING_MODEL}' ...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    collection = _get_collection()

    if args.full:
        filepaths = collect_c_files(args.kernel_path, SUBSYSTEMS)
        print(f"Found {len(filepaths)} C files across configured subsystems.", flush=True)
        total = index_files(filepaths, collection, model)
        print(f"Indexed {total} functions.", flush=True)
    else:
        total = index_files(args.files, collection, model)
        print(f"Indexed {total} functions from {len(args.files)} file(s).", flush=True)


if __name__ == "__main__":
    main()
