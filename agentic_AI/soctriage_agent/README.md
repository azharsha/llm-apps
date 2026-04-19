# SoCTriage

Agentic SoC log analysis system for embedded/GPU bring-up engineers.

## Phase 0 — Foundation

This is the project scaffold. No parsing logic, classification, or LLM calls yet.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```bash
soctriage --list-providers
```

## Development

```bash
mypy soctriage/
pytest tests/test_scaffold.py -v
```
