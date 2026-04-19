"""Cascade analyzer — Phase 4. Re-exports public symbols from cascade.py."""
from soctriage.core.cascade import (  # noqa: F401
    CascadeEdge,
    CascadeResult,
    analyse,
    _break_cycles,
    _has_cycle,
    _get_provider_rules,
)

__all__ = [
    "CascadeEdge", "CascadeResult", "analyse",
    "_break_cycles", "_has_cycle", "_get_provider_rules",
]
