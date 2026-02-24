"""Parse C source files with tree-sitter and extract function metadata."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from tree_sitter import Language, Node, Parser
import tree_sitter_c as tsc

from config import MAX_BODY_SNIPPET_LINES

C_LANGUAGE = Language(tsc.language(), "c")
_parser = Parser()
_parser.set_language(C_LANGUAGE)


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_docstring(node: Node, source: bytes) -> str:
    """Return the block comment immediately preceding the function, if any."""
    prev = node.prev_sibling
    while prev and prev.type in ("comment", "\n", " "):
        if prev.type == "comment":
            raw = _node_text(prev, source)
            # Strip /* ... */ or // markers
            raw = raw.strip()
            if raw.startswith("/*"):
                raw = raw[2:]
                if raw.endswith("*/"):
                    raw = raw[:-2]
            elif raw.startswith("//"):
                raw = raw[2:]
            return raw.strip()
        prev = prev.prev_sibling
    return ""


def _snippet(body: str) -> str:
    lines = body.splitlines()
    if len(lines) <= MAX_BODY_SNIPPET_LINES:
        return body
    return "\n".join(lines[:MAX_BODY_SNIPPET_LINES]) + "\n// ... (truncated)"


def parse_file(filepath: str) -> list[dict]:
    """Return a list of function dicts extracted from a C source file."""
    path = Path(filepath)
    try:
        source = path.read_bytes()
    except OSError:
        return []

    tree = _parser.parse(source)
    results: list[dict] = []

    def walk(node: Node) -> None:
        if node.type == "function_definition":
            # signature: declarator portion
            decl = node.child_by_field_name("declarator")
            body = node.child_by_field_name("body")
            if decl is None or body is None:
                return

            name_node = decl
            # Drill down to the identifier (function name)
            while name_node and name_node.type not in ("identifier",):
                inner = name_node.child_by_field_name("declarator")
                if inner is None:
                    # Try first named child
                    inner = next(
                        (c for c in name_node.children if c.is_named), None
                    )
                if inner is None:
                    break
                name_node = inner

            func_name = _node_text(name_node, source) if name_node else "<unknown>"
            signature = _node_text(decl, source)
            body_text = _node_text(body, source)
            docstring = _extract_docstring(node, source)

            results.append(
                {
                    "name": func_name,
                    "signature": signature,
                    "docstring": docstring,
                    "body_snippet": _snippet(body_text),
                    "file_path": str(path),
                }
            )

        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return results


def parse_files(filepaths: list[str]) -> Generator[dict, None, None]:
    for fp in filepaths:
        yield from parse_file(fp)
