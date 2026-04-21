# SoCTriage — Quickstart

Get running in under 5 minutes.

## Installation

```bash
# Core install (cascade analysis only, no LLM)
pip install soctriage

# With Anthropic Claude LLM backend
pip install soctriage[llm]
```

## First run

```bash
# Analyse a kernel log (no LLM, fast)
soctriage /var/log/dmesg --no-llm

# From stdin
dmesg | soctriage - --no-llm
```

Exit codes: `0` = no anomaly or clean, `1` = critical event found, `2` = error, `3` = usage error.

## With LLM (Anthropic Claude)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
soctriage crash.log
```

The agent runs a tool-calling loop to identify the root cause, suggest fixes, and match
known issues. Results appear in the JSON output under `root_cause`, `fix`, and
`known_issues`.

## Save HTML report

```bash
soctriage crash.log --no-llm --format html --output report.html
# Open report.html in any browser — no internet required
```

## Docker

```bash
# Offline (no LLM)
docker run --rm -v /var/log:/logs:ro sdmove/soctriage dmesg --no-llm

# With LLM
docker run --rm \
  -v /var/log:/logs:ro \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  sdmove/soctriage dmesg
```

## Interpret JSON output

```json
{
  "severity": "critical",
  "root_cause": "GPU firmware failure triggered cascade: GFXHUB → MMHUB → RAS",
  "fix": ["Update firmware to amdgpu 23.40+", "Check PCIe slot for ECC errors"],
  "events": [...],
  "cascade": { ... },
  "ascii_diagram": "..."
}
```

Key fields:
- `severity`: `critical` | `error` | `warning` | `info`
- `root_cause`: LLM narrative (empty string when `--no-llm`)
- `fix`: LLM-generated fix suggestions
- `events`: list of detected anomaly events with `event_type`, `subsystem`, `ip_block`
- `ascii_diagram`: ASCII cascade chain for terminal display

## Next steps

See [architecture.md](architecture.md) for how the pipeline works and
[provider_guide.md](provider_guide.md) to add support for a new SoC vendor.
