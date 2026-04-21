# SoCTriage — Architecture

## Phase Map

| Phase | Name | Key Module | Deliverable |
|---|---|---|---|
| 0 | Foundation + Scaffold | `cli.py`, stubs | All interfaces, CI, fixtures |
| 1 | Input Handler | `core/input_handler.py` | `open_log()`, decompression, streaming |
| 2–2e | Tokenizer + 84 YAML Rules | `core/tokenizer.py`, `core/token_rules/` | `tokenize()`, 280+ token types |
| 3 | Assembler + Classifier | `core/assembler.py`, `core/classifier.py` | `LogEvent`, 15 subsystem classifiers |
| 3c | Hardware Decode | `core/hardware_decode.py`, `core/scan_dump_parser.py` | Register decode, ScanDump parser |
| 4 | Cascade Analyzer | `core/cascade.py`, `core/ascii_diagram.py` | `CascadeResult`, 30 causal rules |
| 5 | Provider Implementations | `providers/*/provider.py` | Intel, Qualcomm, AMD, NVIDIA, Generic |
| 6 | Agentic AI | `core/agent.py`, `core/llm_client.py` | `run_agent()`, Anthropic tool-calling |
| 7 | Reporter + CLI | `core/reporter.py`, `core/html_renderer.py`, `cli.py` | `report()`, JSON/MD/HTML, exit codes |
| 8 | Production Hardening | `pyproject.toml`, CI, docs | PyPI, Docker, benchmarks, completions |

## Data Flow

```
Input log (.log / .gz / .bz2 / .xz / stdin)
    │
    ▼
open_log()          → lines: Iterator[str], meta: InputMeta
    │
    ▼
tokenize()          → tokens: list[LogToken]
    │
    ▼
assemble()          → raw events: Iterator[LogEvent]
    │
    ▼
classify_all()      → classified events: list[LogEvent]
    │
    ▼
decode_hardware()   → events with .hardware_context attached
    │
    ▼
analyse()           → CascadeResult (root cause, edges, severity)
    │
    ▼
run_agent()         → AgentResult (narrative, fix suggestions, tool trace)
    │
    ▼
report()            → JSON / Markdown / HTML string
```

## Module Tree

```
soctriage/
├── cli.py                          # Entry point: main(argv) -> int
├── providers/
│   ├── __init__.py                 # get_all_providers()
│   ├── intel/provider.py           # IntelProvider
│   ├── qualcomm/provider.py        # QualcommProvider
│   ├── amd/provider.py             # AMDProvider
│   ├── nvidia/provider.py          # NVIDIAProvider
│   └── generic/provider.py         # GenericProvider
└── core/
    ├── input_handler.py            # open_log(), InputError, InputMeta
    ├── token_rule.py               # TokenRule, TokenRuleRegistry
    ├── tokenizer.py                # tokenize()
    ├── assembler.py                # assemble(), LogEvent, LogToken
    ├── classifier.py               # classify_all()
    ├── hardware_decode.py          # decode_hardware()
    ├── scan_dump_parser.py         # ScanDumpParser
    ├── cascade.py                  # analyse(), CascadeResult, CascadeEdge
    ├── ascii_diagram.py            # render() → ASCII cascade diagram
    ├── reporter.py                 # report(), render_json(), render_markdown()
    ├── html_renderer.py            # render_html()
    ├── agent.py                    # run_agent()
    ├── agent_result.py             # AgentResult, ToolCall
    ├── llm_client.py               # AnthropicClient, OllamaClient
    ├── tool_registry.py            # ToolSpec, ToolRegistry
    ├── prompts.py                  # System prompt templates
    ├── soc_provider.py             # SoCProvider ABC
    ├── provider_registry.py        # ProviderRegistry
    └── token_rules/                # 84 YAML rule files
        ├── gpu.yaml
        ├── amd_platform.yaml
        └── ...
```

## Provider Detection

At startup, the CLI reads the first 500 lines of the log (`head_text`) and passes them
to `ProviderRegistry.detect_provider(head_text)`. Each `SoCProvider.detect(raw_log: str)`
returns a confidence score; the highest-confidence provider wins.

If `--soc-provider` is given, the named provider is selected directly.

## Key Invariants

- `LogToken` is immutable (frozen dataclass)
- `LogEvent` is immutable (frozen dataclass)
- `CascadeResult` is immutable (frozen dataclass)
- `AgentResult` is immutable (frozen dataclass)
- `report()` never raises — returns error JSON on failure
- All exit codes: 0=OK, 1=critical, 2=error, 3=usage
