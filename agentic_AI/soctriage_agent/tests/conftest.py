"""
conftest.py — shared pytest fixtures for SoCTriage tests.

Fixture hierarchy (from cheapest to most expensive):
  load_fixture(vendor, name)     → raw log text (str)
  iter_fixture(vendor, name)     → line iterator over fixture file
  tokenize_fixture(vendor, name) → list[LogToken] (isolated registry)
  assemble_fixture(vendor, name) → list[LogEvent]
  classify_fixture(vendor, name) → list[LogEvent] (with classifier applied)
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from soctriage.core.token_rule import TokenRuleRegistry
from soctriage.core.tokenizer import LogToken, tokenize
from soctriage.core.assembler import LogEvent, assemble
from soctriage.core.classifier import classify_all

FIXTURES_DIR: Path = Path(__file__).parent / "fixtures"


# ── Low-level helpers ─────────────────────────────────────────────────────────


def _fixture_path(vendor: str, name: str) -> Path:
    """Return the absolute path to a fixture file."""
    path = FIXTURES_DIR / vendor / name
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    return path


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def fresh_registry() -> TokenRuleRegistry:
    """
    A single TokenRuleRegistry loaded once per test session.
    Tests that need a clean registry can call TokenRuleRegistry() directly.
    """
    r = TokenRuleRegistry()
    r.load_defaults()
    return r


@pytest.fixture
def load_fixture():
    """
    Return a callable: load_fixture(vendor, name) -> str.

    Usage:
        def test_foo(load_fixture):
            text = load_fixture("intel", "guc_hang.log")
    """
    def _load(vendor: str, name: str) -> str:
        return _fixture_path(vendor, name).read_text(encoding="utf-8", errors="replace")
    return _load


@pytest.fixture
def iter_fixture():
    """
    Return a callable: iter_fixture(vendor, name) -> Iterator[str].
    Each call opens the file fresh.
    """
    def _iter(vendor: str, name: str) -> Iterator[str]:
        path = _fixture_path(vendor, name)
        return iter(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return _iter


@pytest.fixture
def tokenize_fixture(fresh_registry):
    """
    Return a callable: tokenize_fixture(vendor, name) -> list[LogToken].
    Uses the session-scoped registry so YAML is only loaded once.
    """
    def _tokenize(vendor: str, name: str) -> list[LogToken]:
        path = _fixture_path(vendor, name)
        lines = iter(path.read_text(encoding="utf-8", errors="replace").splitlines())
        return list(tokenize(lines, rule_registry=fresh_registry))
    return _tokenize


@pytest.fixture
def assemble_fixture(fresh_registry):
    """
    Return a callable: assemble_fixture(vendor, name) -> list[LogEvent].
    Tokenizes and assembles without classification.
    """
    def _assemble(vendor: str, name: str, provider=None) -> list[LogEvent]:
        path = _fixture_path(vendor, name)
        lines = iter(path.read_text(encoding="utf-8", errors="replace").splitlines())
        tokens = tokenize(lines, rule_registry=fresh_registry)
        return list(assemble(tokens, provider=provider))
    return _assemble


@pytest.fixture
def classify_fixture(fresh_registry):
    """
    Return a callable: classify_fixture(vendor, name) -> list[LogEvent].
    Full Phase 1-3 pipeline (tokenize -> assemble -> classify).
    """
    def _classify(vendor: str, name: str, provider=None) -> list[LogEvent]:
        path = _fixture_path(vendor, name)
        lines = iter(path.read_text(encoding="utf-8", errors="replace").splitlines())
        tokens = tokenize(lines, rule_registry=fresh_registry)
        events = assemble(tokens, provider=provider)
        return list(classify_all(events, provider=provider))
    return _classify


# ── Parametrize helpers ───────────────────────────────────────────────────────


def all_fixtures() -> list[tuple[str, str]]:
    """Return all (vendor, filename) pairs found under tests/fixtures/."""
    result: list[tuple[str, str]] = []
    if FIXTURES_DIR.exists():
        for vendor_dir in sorted(FIXTURES_DIR.iterdir()):
            if vendor_dir.is_dir():
                for log_file in sorted(vendor_dir.glob("*.log")):
                    result.append((vendor_dir.name, log_file.name))
    return result


def vendor_fixtures(vendor: str) -> list[str]:
    """Return all fixture filenames for a given vendor."""
    vendor_dir = FIXTURES_DIR / vendor
    if not vendor_dir.exists():
        return []
    return [f.name for f in sorted(vendor_dir.glob("*.log"))]
