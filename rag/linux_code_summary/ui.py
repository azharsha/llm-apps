"""Streamlit UI for Linux kernel code search."""

from __future__ import annotations

import chromadb
import streamlit as st

from config import CHROMA_DIR, COLLECTION_NAME
from retriever import search, search_with_summaries

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Linux Kernel Code Search",
    page_icon="🐧",
    layout="wide",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🐧 Kernel Search")
    st.markdown("Semantic search over indexed Linux kernel functions powered by ChromaDB + Claude.")

    st.divider()

    limit = st.slider("Number of results", min_value=1, max_value=20, value=5)
    use_summaries = st.toggle(
        "Claude summaries",
        value=True,
        help="Ask Claude to explain each result in context of your query (slower)",
    )

    st.divider()

    # Stats
    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        col = client.get_or_create_collection(COLLECTION_NAME)
        count = col.count()
        st.metric("Indexed functions", f"{count:,}")
    except Exception as e:
        st.warning(f"Could not load stats: {e}")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_body(document: str, signature: str) -> str:
    """Return the body snippet portion of the stored document text."""
    lines = document.splitlines()
    # Skip header lines added by _func_document (Function:, Signature:, Doc:)
    skip_prefixes = ("Function:", "Signature:", "Doc:")
    body_lines = []
    for line in lines:
        if any(line.startswith(p) for p in skip_prefixes):
            continue
        body_lines.append(line)
    return "\n".join(body_lines).strip()


# ── Main area ─────────────────────────────────────────────────────────────────

st.title("Linux Kernel Code Search")
st.caption("Query the indexed kernel subsystems using natural language.")

query = st.text_input(
    "Search",
    placeholder="e.g. task scheduling fairness, spinlock acquire, context switch",
    label_visibility="collapsed",
)

search_btn = st.button("Search", type="primary", use_container_width=False)

if search_btn and query.strip():
    with st.spinner("Searching…" if not use_summaries else "Searching and generating summaries…"):
        try:
            if use_summaries:
                hits = search_with_summaries(query, limit=limit)
            else:
                hits = search(query, limit=limit)
        except Exception as e:
            st.error(f"Search failed: {e}")
            hits = []

    if not hits:
        st.info("No results found.")
    else:
        st.success(f"{len(hits)} result(s) for **{query}**")
        for i, hit in enumerate(hits, 1):
            meta = hit["metadata"]
            score = hit.get("score", 0.0)
            name = meta.get("name", "unknown")
            file_path = meta.get("file_path", "")
            signature = meta.get("signature", "")
            docstring = meta.get("docstring", "")
            summary = hit.get("summary")
            body = _extract_body(hit.get("document", ""), signature)

            with st.expander(f"**{i}. `{name}`** — score {score:.3f}", expanded=(i == 1)):
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.markdown(f"**File:** `{file_path}`")
                with c2:
                    st.markdown(f"**Score:** `{score:.4f}`")

                if docstring:
                    st.markdown(f"_{docstring}_")

                if summary:
                    st.markdown("**Summary:**")
                    st.markdown(summary)
                    st.divider()

                st.markdown("**Function body:**")
                st.code(body or signature, language="c")

elif search_btn and not query.strip():
    st.warning("Please enter a search query.")
