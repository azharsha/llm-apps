# Changelog

All notable changes to SoCTriage are documented here.

## [1.0.0] — 2026-04-21 (Phase 8 — Production Hardening)

**Production packaging and distribution.**

- PyPI-ready `pyproject.toml`: hatchling build backend, classifiers, `[llm]`/`[dev]` extras
- Multi-stage `Dockerfile` + `docker-compose.yml` (cloud, offline, Ollama profiles)
- Bash, Zsh, Fish shell completions (`completions/`)
- Man page `soctriage(1)` (`man/soctriage.1`)
- `pytest-benchmark` suite: 7 performance benchmarks with regression guards
- `.pre-commit-config.yaml`: ruff, mypy, pytest-smoke, yamllint
- `.devcontainer/devcontainer.json` for VS Code / GitHub Codespaces
- GitHub Actions: PR matrix gate (Python 3.11/3.12/3.13) + PyPI release workflow
- `docs/`: quickstart, architecture, provider guide, YAML guide, CLI reference, API reference
- `tests/test_packaging.py`: 15 packaging smoke tests
- **Tests: ~1083 passed · 0 failed**

## [0.8.0] — 2026-04-20 (Phase 7 — Reporter + CLI Hardening)

**Unified output and CLI hardening.**

- `report(AgentResult, fmt, output)` — never-raises unified formatter
- HTML renderer (`html_renderer.py`) — stdlib-only, inline CSS, no external URLs
- Exit code aliases: `EXITOK=0`, `EXITCRITICAL=1`, `EXITERROR=2`, `EXITUSAGE=3`
- `main(argv=None) -> int` — injectable argv for tests
- New CLI flags: `--no-llm`, `--llm-backend`, `--llm-model`, `--ollama-host`,
  `--timeout`, `--include-raw`, `--version`, positional `LOG_FILE`
- `get_all_providers()` in `providers/__init__.py`
- `OUTPUTSCHEMA` (19-key JSON contract)
- Phase 7 fixture logs for 4 vendors + generic empty + nocrash
- **Tests: 1048 passed · 6 xfailed · 0 failed**

## [0.7.0] — 2026-04-19 (Phase 6.1.0 — Anthropic Claude Backend)

**Replaced OpenAI with Anthropic Claude.**

- `AnthropicClient`: Anthropic message format (`tool_use`/`tool_result` blocks,
  system as top-level param)
- `OllamaClient`: Ollama REST API with OpenAI-compatible tool schema
- `to_anthropic_schema()` replaces `to_openai_schema()` (`input_schema` key)
- `run_agent()` defaults: `backend="anthropic"`, `model="claude-sonnet-4-5"`
- Stop-reason strings: `"end_turn"` / `"tool_use"` / `"max_tokens"`
- **Tests: 968 passed · 0 failed**

## [0.6.0] — 2026-04-18 (Phase 6 — Agentic AI)

**Tool-calling LLM agent for root-cause analysis.**

- `run_agent()` — agentic loop with tool registry
- `AgentResult` — root_cause_narrative, fix_suggestions, known_issues_matched,
  confidence, tool_trace, total_ms
- `ToolRegistry` + `ToolSpec` — `to_anthropic_schema()`
- `AnthropicClient` / `OllamaClient` — backend abstraction
- System prompt with SoC context injection
- **Tests: 943 passed · 0 failed**

## [0.5.0] — 2026-04-17 (Phase 5 — Provider Implementations)

**Five concrete SoC provider implementations.**

- `IntelProvider`: i915, GuC, GSC detection + Gen12/Xe register decode
- `QualcommProvider`: ADSP/MODEM/GPU crash detection + SSR state decode
- `AMDProvider`: amdgpu, PSP, RAS detection + CDNA register decode
- `NVIDIAProvider`: XID error detection + GSP firmware decode
- `GenericProvider`: fallback (confidence 0.1)
- `ProviderRegistry.auto_discover()`
- **Tests: 818 passed · 0 failed**

## [0.4.0] — 2026-04-16 (Phase 4 — Cascade Analyzer)

**Causal chain analysis.**

- `analyse(events) -> CascadeResult` — 30 causal rules, topological sort
- `CascadeEdge` — source_id, target_id, relation, confidence, reasoning
- `render()` — ASCII cascade diagram
- EC-27 performance gate: 10k events < 500ms
- **Tests: 683 passed · 0 failed**

## [0.3c.0] — 2026-04-15 (Phase 3c — Hardware Decode)

**Register-level hardware decode.**

- `decode_hardware()` — attaches `hardware_context` to events
- `ScanDumpParser` — parses kernel scan_dump / register dumps
- Intel, AMD, Qualcomm, NVIDIA register decode tables
- **Tests: 638 passed · 0 failed**

## [0.3.0] — 2026-04-14 (Phase 3 — Assembler + Classifier)

**Token → LogEvent assembly and classification.**

- `assemble()` — groups tokens into `LogEvent` objects
- `classify_all()` — 15 subsystem classifiers (gpu, cpu, memory, pcie, storage, ...)
- `LogEvent` frozen dataclass
- **Tests: 568 passed · 0 failed**

## [0.2e.0] — 2026-04-12 (Phase 2e — Plugin API + CLI Extensibility)

**Runtime extensibility.**

- `--token-rule TYPE:PATTERN` inline rule injection
- `--plugin PATH` Python plugin loading with `@register_rule`
- `PluginLoader` + `TokenRuleRegistry.register()`
- **Tests: 508 passed · 0 failed**

## [0.2.0] — 2026-04-10 (Phase 2 — Tokenizer + 84 YAML Rules)

**Core tokenizer and rule engine.**

- `tokenize()` — streaming log tokenizer
- `TokenRule`, `TokenRuleRegistry`, `TokenContext`
- 84 YAML rule files, 280+ token types across all subsystems
- **Tests: ~388 passed · 0 failed**

## [0.1.0] — 2026-04-08 (Phase 1 — Input Handler)

**Log ingestion.**

- `open_log()` — reads `.log`, `.gz`, `.bz2`, `.xz`, stdin
- `InputMeta` — source path, size, compression hint
- `InputError` with structured error codes
- **Tests: 28 passed · 0 failed**

## [0.0.0] — 2026-04-07 (Phase 0 — Foundation + Scaffold)

**Project skeleton, stubs, CI.**

- All module stubs and interfaces
- pytest infrastructure, fixtures, conftest
- mypy + ruff configuration
- Phase 0 xfail scaffold tests
- **Tests: 20 passed · 0 failed**
