# SoCTriage — CLI Reference

## Synopsis

```
soctriage [OPTIONS] LOG_FILE
soctriage [OPTIONS] --input PATH
soctriage - [OPTIONS]          # stdin
```

## Positional Arguments

| Argument | Description |
|---|---|
| `LOG_FILE` | Kernel log file (`.log`, `.gz`, `.bz2`, `.xz`) or `-` for stdin |

## Options

### Input / Output

| Flag | Default | Description |
|---|---|---|
| `--input PATH` | — | Input log file path, or `-` for stdin (alias for positional) |
| `--output PATH` | — | Output report base path (extension added per `--format`) |
| `--format {json,markdown,html}` | `json` | Output format |
| `--include-raw` | off | Include raw event text in JSON output |

### LLM Control

| Flag | Default | Description |
|---|---|---|
| `--no-llm` | off | Skip LLM agent — Phase 4 cascade analysis only |
| `--llm-backend {anthropic,ollama}` | `anthropic` | LLM backend |
| `--llm-model MODEL` | `claude-sonnet-4-5` | LLM model name |
| `--ollama-host URL` | `http://localhost:11434` | Ollama API host |
| `--timeout SECS` | `60` | LLM call timeout in seconds |

### SoC / Hardware

| Flag | Description |
|---|---|
| `--asic-gen GEN` | Override ASIC/chip generation detection |
| `--soc-provider NAME` | Force specific SoC provider by name |
| `--list-providers` | List all registered providers and exit |

### Extensibility

| Flag | Description |
|---|---|
| `--token-rule TYPE:PATTERN` | Inject an inline token rule. Repeatable. |
| `--plugin PATH` | Load a Python plugin file with `@register_rule` rules. Repeatable. |

### Utility

| Flag | Description |
|---|---|
| `--verbose` | Enable debug output |
| `--version` | Show soctriage version and exit |

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success — no critical events found |
| `1` | Critical severity event detected |
| `2` | Runtime error (file not found, parse error, agent failure) |
| `3` | Usage error (bad arguments) |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(none)* | Required for `--llm-backend anthropic` |
| `OLLAMA_HOST` | `http://localhost:11434` | Override Ollama host without CLI flag |
| `SOCTRIAGE_RULES_DIR` | bundled `token_rules/` | Override YAML rules directory |
| `SOCTRIAGE_LOG_LEVEL` | `WARNING` | Python logging level |
| `NO_COLOR` | *(unset)* | Disable ANSI colour when set |

## Examples

```bash
# Basic analysis, no LLM
soctriage /var/log/dmesg --no-llm

# Save JSON report
soctriage crash.log --no-llm --output report.json

# Save HTML report
soctriage crash.log --no-llm --format html --output report.html

# Full analysis with Anthropic Claude
export ANTHROPIC_API_KEY=sk-ant-...
soctriage crash.log

# Force AMD provider
soctriage crash.log --soc-provider amd --no-llm

# Inject an inline token rule
soctriage crash.log --token-rule "my_event:my_pattern" --no-llm

# Load a plugin
soctriage crash.log --plugin plugins/my_rules.py --no-llm

# Use Ollama locally
soctriage crash.log --llm-backend ollama --llm-model llama3.2 --ollama-host http://localhost:11434

# Read from stdin
dmesg | soctriage - --no-llm

# Compressed log
soctriage crash.log.gz --no-llm
```
