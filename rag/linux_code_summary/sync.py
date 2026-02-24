"""Incremental sync: git-fetch the kernel repo, detect changed files, re-index them.

Usage:
    python sync.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from config import (
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    KERNEL_PATH,
    LAST_COMMIT_FILE,
    SUBSYSTEMS,
)
from indexer import index_files


def _run(cmd: list[str], cwd: str) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _read_last_commit() -> str | None:
    path = Path(LAST_COMMIT_FILE)
    if path.exists():
        return path.read_text().strip() or None
    return None


def _write_last_commit(sha: str) -> None:
    Path(LAST_COMMIT_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(LAST_COMMIT_FILE).write_text(sha)


def _changed_c_files(repo: str, old_sha: str, new_sha: str) -> list[str]:
    """Return C files changed between two commits that belong to a configured subsystem."""
    diff = _run(["git", "diff", "--name-only", old_sha, new_sha], cwd=repo)
    if not diff:
        return []

    changed = []
    for line in diff.splitlines():
        if not line.endswith(".c"):
            continue
        if any(line.startswith(sub) for sub in SUBSYSTEMS):
            full_path = str(Path(repo) / line)
            if Path(full_path).exists():
                changed.append(full_path)
    return changed


def sync(kernel_path: str = KERNEL_PATH) -> dict:
    repo = kernel_path
    if not repo:
        raise ValueError("kernel_path is not set. Add KERNEL_PATH to your .env or pass it explicitly.")

    print(f"Fetching latest commits in '{repo}' ...")
    _run(["git", "fetch", "--quiet"], cwd=repo)
    new_sha = _run(["git", "rev-parse", "FETCH_HEAD"], cwd=repo)

    old_sha = _read_last_commit()
    if old_sha is None:
        print("No previous commit recorded. Run `python indexer.py --full` first.")
        return {"status": "no_baseline", "new_sha": new_sha}

    if old_sha == new_sha:
        print("Already up to date.")
        return {"status": "up_to_date", "sha": new_sha}

    changed = _changed_c_files(repo, old_sha, new_sha)
    print(f"Detected {len(changed)} changed C file(s) in monitored subsystems.")

    indexed = 0
    if changed:
        model = SentenceTransformer(EMBEDDING_MODEL)
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_or_create_collection(COLLECTION_NAME)
        indexed = index_files(changed, collection, model)
        print(f"Re-indexed {indexed} function(s).")

    _write_last_commit(new_sha)
    return {
        "status": "updated",
        "old_sha": old_sha,
        "new_sha": new_sha,
        "files_changed": len(changed),
        "functions_indexed": indexed,
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Incremental kernel sync")
    ap.add_argument(
        "--kernel-path",
        default=KERNEL_PATH,
        metavar="PATH",
        help="Path to the kernel source tree (overrides KERNEL_PATH env var)",
    )
    a = ap.parse_args()
    result = sync(kernel_path=a.kernel_path)
    print(result)
