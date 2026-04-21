# SoCTriage

AI-powered Linux kernel / SoC crash diagnostic tool for embedded and GPU bring-up engineers.

SoCTriage analyses kernel crash logs and SoC diagnostic dumps to identify the root cause
of hardware failures, classify subsystem events into a causal chain, and generate
structured reports — with or without an LLM backend.

---

## Features

- **Multi-vendor SoC support** — Intel (i915/GuC), Qualcomm (ADSP/MODEM/GPU), AMD (amdgpu/PSP/RAS), NVIDIA (GSP/XID), Generic
- **280+ token types** — 84 YAML rule files covering GPU, PCIe, RAS, CXL, memory, storage, network, platform crashes
- **Cascade analysis** — 30 causal rules that trace a fault chain from root cause to downstream effects
- **Hardware register decode** — per-vendor register table decode with ScanDump parser
- **Agentic LLM analysis** — Anthropic Claude or Ollama tool-calling loop for root-cause narratives and fix suggestions
- **Three output formats** — JSON (machine-readable), Markdown, HTML (offline, no CDN)
- **Compressed log support** — `.gz`, `.bz2`, `.xz` transparently decompressed
- **Extensible** — inline `--token-rule` injection and `--plugin` Python API

---

## Installation

```bash
# Core install — cascade analysis, no LLM required
pip install soctriage

# With Anthropic Claude LLM backend
pip install soctriage[llm]
```

**Requirements:** Python 3.11+, Linux.

---

## Quick Start

```bash
# Analyse a kernel dmesg (no LLM, fast)
soctriage /var/log/dmesg --no-llm

# Read from stdin
dmesg | soctriage - --no-llm

# With Anthropic Claude for root-cause narrative + fix suggestions
export ANTHROPIC_API_KEY=sk-ant-...
soctriage crash.log
```

---

## Output Formats

### JSON (default)

```bash
soctriage crash.log --no-llm
soctriage crash.log --no-llm --output report.json
```

```json
{
  "version": "1.0",
  "provider": "amd",
  "chip_gen": "amd_cdna3",
  "severity": "critical",
  "root_cause": "GPU firmware failure triggered cascade: GFXHUB → MMHUB → RAS",
  "fix": ["Update amdgpu firmware to 23.40+", "Check PCIe slot ECC error counters"],
  "known_issues": [],
  "events": [
    {
      "event_id": 0,
      "event_type": "gpu_firmware_fail",
      "subsystem": "gpu",
      "ip_block": "GFX",
      "severity": "critical",
      "confidence": 0.95,
      "start_line": 42,
      "end_line": 47
    }
  ],
  "cascade": { ... },
  "ascii_diagram": "gpu_firmware_fail ──triggers──▶ gpu_hang\n  gpu_hang ──causes──▶ ras_error",
  "confidence": 0.91,
  "llm_backend": "none",
  "analysis_ms": 18
}
```

### Markdown

```bash
soctriage crash.log --no-llm --format markdown
soctriage crash.log --no-llm --format markdown --output report.md
```

### HTML (offline, no internet required)

```bash
soctriage crash.log --no-llm --format html --output report.html
# Open report.html in any browser
```

### Include raw event text

```bash
soctriage crash.log --no-llm --include-raw
```

---

## LLM Backends

### Anthropic Claude (default)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
soctriage crash.log --llm-backend anthropic --llm-model claude-sonnet-4-5
```

### Ollama (local, offline)

```bash
# Start Ollama and pull a model first
ollama pull llama3.2

soctriage crash.log --llm-backend ollama --llm-model llama3.2
soctriage crash.log --llm-backend ollama --ollama-host http://localhost:11434
```

### Skip LLM entirely

```bash
soctriage crash.log --no-llm
```

---

## SoC Provider Selection

SoCTriage auto-detects the vendor from log content. Override manually:

```bash
# Force AMD provider
soctriage crash.log --soc-provider amd --no-llm

# Force Qualcomm provider
soctriage crash.log --soc-provider qualcomm --no-llm

# List all registered providers
soctriage --list-providers
# Registered providers:
#   intel
#   qualcomm
#   amd
#   nvidia
#   generic
```

---

## Extensibility

### Inline token rule injection

```bash
# Inject a single rule at runtime (no file needed)
soctriage crash.log --token-rule "cxl_fatal:CXL 3.0: fatal" --no-llm

# Multiple rules
soctriage crash.log \
  --token-rule "cxl_fatal:CXL 3.0: fatal" \
  --token-rule "cxl_fatal:cxl_mem: unrecoverable" \
  --no-llm
```

### Python plugin file

```python
# plugins/my_rules.py
from soctriage.core.plugin import register_rule

@register_rule(priority=145)
class MyCustomRule:
    token_type = "my_event"
    patterns   = ["MY_DEVICE: fatal error", "my_driver: crash"]
    arch       = "any"
    providers  = ["any"]
```

```bash
soctriage crash.log --plugin plugins/my_rules.py --no-llm
```

---

## Docker

```bash
# Pull and run (offline, no LLM)
docker run --rm -v /var/log:/logs:ro sdmove/soctriage dmesg --no-llm

# With Anthropic Claude
docker run --rm \
  -v /var/log:/logs:ro \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  sdmove/soctriage dmesg

# Build locally
docker build -t soctriage .
docker run --rm -v ./logs:/logs:ro soctriage crash.log --no-llm
```

Or with `docker-compose`:

```bash
# Offline
docker compose --profile offline up

# With Ollama sidecar
docker compose --profile ollama up
```

---

## Shell Completions

```bash
# Bash
source completions/soctriage.bash

# Zsh
cp completions/soctriage.zsh /usr/share/zsh/site-functions/_soctriage

# Fish
cp completions/soctriage.fish ~/.config/fish/completions/soctriage.fish
```

Or use the Makefile to install system-wide:

```bash
sudo make install-completions
```

---

## Man Page

```bash
man ./man/soctriage.1
```

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success — no critical events found |
| `1` | Critical severity event detected |
| `2` | Runtime error (file not found, parse failure, agent error) |
| `3` | Usage error (bad arguments) |

Useful in shell scripts:

```bash
soctriage crash.log --no-llm && echo "Clean" || echo "Problems found (exit $?)"
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for `--llm-backend anthropic` |
| `OLLAMA_HOST` | `http://localhost:11434` | Override Ollama host without CLI flag |
| `SOCTRIAGE_RULES_DIR` | bundled | Override YAML token rules directory |
| `SOCTRIAGE_LOG_LEVEL` | `WARNING` | Python logging level |
| `NO_COLOR` | — | Disable ANSI colour when set |

---

## All CLI Flags

```
soctriage [OPTIONS] LOG_FILE

Positional:
  LOG_FILE                  Log file (.log .gz .bz2 .xz) or - for stdin

Input/Output:
  --input PATH              Input log file (alias for positional)
  --output PATH             Output report path
  --format {json,markdown,html}  Output format (default: json)
  --include-raw             Include raw event text in JSON

LLM:
  --no-llm                  Skip LLM — cascade analysis only
  --llm-backend {anthropic,ollama}  (default: anthropic)
  --llm-model MODEL         (default: claude-sonnet-4-5)
  --ollama-host URL         (default: http://localhost:11434)
  --timeout SECS            LLM timeout (default: 60)

Hardware:
  --asic-gen GEN            Override chip generation detection
  --soc-provider NAME       Force provider (intel/qualcomm/amd/nvidia/generic)
  --list-providers          List providers and exit

Extensibility:
  --token-rule TYPE:PATTERN Inject inline token rule (repeatable)
  --plugin PATH             Load Python plugin (repeatable)

Utility:
  --verbose                 Debug output
  --version                 Show version and exit
```

---

## Development

```bash
git clone https://github.com/sdmove/soctriage
cd soctriage
pip install -e ".[dev,llm]"
pre-commit install

pytest --tb=short -q          # full test suite (~1072 tests)
pytest benchmarks/ --benchmark-only -q  # performance benchmarks
mypy soctriage/               # type check
ruff check soctriage/ tests/  # lint
```

Or open in VS Code — a dev container configuration is included (`.devcontainer/`).

See [CONTRIBUTING.md](CONTRIBUTING.md) for adding token rules, providers, and plugins.
See [docs/](docs/) for architecture, API reference, and guides.

---

## Documentation

| Doc | Description |
|---|---|
| [docs/quickstart.md](docs/quickstart.md) | 5-minute install and first-run guide |
| [docs/architecture.md](docs/architecture.md) | Full phase map, data flow, module tree |
| [docs/provider_guide.md](docs/provider_guide.md) | How to add a new SoC vendor |
| [docs/yaml_guide.md](docs/yaml_guide.md) | How to write YAML token rules |
| [docs/cli_reference.md](docs/cli_reference.md) | Complete CLI flag reference |
| [docs/api_reference.md](docs/api_reference.md) | Public Python API |

---

## License

MIT — see [LICENSE](LICENSE).
