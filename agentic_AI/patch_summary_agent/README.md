# LKML Patch Summary Agent

An AI-powered tool that fetches recent Linux kernel patches from [patchwork.kernel.org](https://patchwork.kernel.org), autonomously analyses them using Claude, and produces a structured technical digest — in the terminal and as a self-contained HTML report.

## What it does

1. **Fetches** patches from the Patchwork REST API, filtered by project, date range, and optional keyword
2. **Groups** patches into their patch series (cover letter + numbered patches)
3. **Analyses** each series by calling Claude with the full diff, commit message, and metadata
4. **Detects** the kernel subsystem automatically (USB, DRM/GPU, Network, Filesystem, etc.)
5. **Flags** ABI concerns, removed exported symbols, UAPI header changes, ioctl modifications, and breaking changes
6. **Writes** a structured digest to the terminal using Rich formatting
7. **Generates** a dark-themed, filterable HTML report saved locally

## Architecture

```
patch_summary_agent/
├── main.py                  # CLI entry point — argument parsing, terminal output, HTML save
├── config.py                # API keys, model name, limits
├── agents/
│   ├── orchestrator.py      # Agentic loop: runs Claude with tools until digest is complete
│   └── tools.py             # Tool schemas and dispatch (fetch / detail / series)
├── fetcher/
│   ├── patchwork.py         # Patchwork REST API client with retry/backoff
│   └── parser.py            # Diff parser, subsystem detector, ABI flag checker
└── digest/
    └── generator.py         # HTML report renderer (Jinja2 template)
```

### Agentic loop

The orchestrator (`agents/orchestrator.py`) runs a Claude tool-use loop:

```
User prompt → Claude → tool_use blocks → tool results → Claude → … → end_turn
```

Claude autonomously decides which tools to call and in what order, up to `MAX_AGENT_ITERATIONS` (40) turns. Three tools are exposed:

| Tool | Purpose |
|------|---------|
| `fetch_recent_patches` | List recent patches (metadata only) |
| `get_patch_details` | Full diff, files changed, subsystem, ABI flags for one patch |
| `get_series_patches` | All patches in a named series + cover letter excerpt |

### Subsystem detection

`fetcher/parser.py` detects the kernel subsystem using two strategies in order:

1. **Subject prefix** — parses `[PATCH v2 2/4] usb: ehci: fix …` bracket tags
2. **File path scoring** — scores each changed file against ~60 path regex patterns and picks the best match

Recognised subsystems include USB, DRM/GPU, SCSI, NVMe, Wi-Fi/Wireless, Bluetooth, Network, all major filesystems, CPU architectures, Memory Management, Scheduler, KVM, BPF/Tracing, Security/LSM, Crypto, and many more.

### ABI / breaking-change detection

The agent flags patches that:
- Remove `EXPORT_SYMBOL` / `EXPORT_SYMBOL_GPL` entries
- Modify files under `include/uapi/` (userspace ABI)
- Remove or change `ioctl` definitions
- Mention "ABI break", "API change", or "backward compatibility removed"
- Remove `__deprecated` annotations
- Rename exported symbols
- Remove `sysfs` or `debugfs` entries

### Memory leak detection

`fetcher/parser.py` runs static heuristics over every diff to surface potential memory and resource leaks. These are passed to Claude as `memory_leak_flags` so it can reason about them in context.

**Static signals detected:**

| Pattern | What it catches |
|---------|----------------|
| Removed `kfree` / `vfree` / `kvfree` / `kfree_sensitive` | Explicit heap free deleted |
| Removed `kmem_cache_free` | Slab cache free deleted |
| Removed `kfree_skb` / `consume_skb` | sk_buff free deleted |
| Removed `put_device` / `kobject_put` / `kref_put` / `of_node_put` / etc. | Reference count or resource put removed |
| Removed `free_irq` / `devm_free_irq` | IRQ release removed |
| Removed `release_firmware` | Firmware object release removed |
| Removed `dma_free_coherent` / `dma_unmap_*` | DMA buffer or mapping release removed |
| Removed `err_free:` / `cleanup:` / `unwind:` goto labels | Error-path cleanup code deleted |
| Added `kmalloc` / `kzalloc` / `vmalloc` / `devm_kmalloc` etc. | New heap allocation — verify all error paths free it |
| Added `return -Exxx` / `return PTR_ERR(...)` | New early error return — may skip cleanup of preceding allocations |
| Commit message mentions "memory leak" / "resource leak" / "use-after-free" | Explicit leak mention in description |

Claude then reasons holistically about the diff to confirm, dismiss, or expand on these hints, and reports findings under a dedicated **Memory Leaks** field in the digest.

## Requirements

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)

## Installation

```bash
git clone <repo>
cd patch_summary_agent
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-...
```

## Usage

```bash
# Fetch last day of patches across all projects (default: 15 patches)
python main.py

# Fetch last 2 days, up to 20 patches
python main.py --limit 20 --days 2

# Target a specific Patchwork project
python main.py --project linux-usb --days 1
python main.py --project netdev --days 2
python main.py --project dri-devel --limit 30

# Further filter by keyword within a project
python main.py --project linux-usb --subsystem EHCI --limit 20
python main.py --project netdev --subsystem iwlwifi

# List all available Patchwork project names (no API key needed)
python main.py --list-projects

# Specify a custom HTML output path
python main.py --output /tmp/my_report.html
```

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--limit N` | 15 | Max patches to fetch (capped at 50 per API call) |
| `--days N` | 1 | Days of history to cover (fractional values OK, e.g. `0.5`) |
| `--project NAME` | all | Patchwork `link_name` to restrict to (e.g. `linux-usb`, `netdev`, `dri-devel`) |
| `--subsystem KEYWORD` | none | Case-insensitive keyword filter on patch subjects within the project results |
| `--output PATH` | auto | HTML report path (default: `lkml_digest_<project>_<YYYYMMDD>.html`) |
| `--list-projects` | — | Print all available Patchwork project names and exit |

## Output

### Terminal

Rich-formatted digest printed directly to stdout:

```
╭─────────────────────────────────────╮
│ LKML Patch Summary Agent            │
│ AI-powered Linux kernel patch digest│
╰─────────────────────────────────────╯

════════════════ LKML DIGEST ════════════════

### [USB] — ehci: fix suspend race in port reset
**Submitter**: Jane Dev <jane@example.com>
**Type**: bug-fix
**Impact**: Moderate
**Patches**: 2 patch(es)   **State**: accepted
...
```

### HTML report

A self-contained dark-themed HTML file (`lkml_digest_<slug>_<date>.html`) with:
- Stats bar: patches fetched, series analysed, digest entries, flagged count
- Filterable patch cards by subsystem, impact level, or flagged status
- Per-card colour coding: red border = Major impact, yellow = Moderate, green = Minor
- Red left border on cards with ABI/breaking-change flags
- Collapsible raw agent digest at the bottom

## Configuration

All tunable values live in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `MODEL` | `claude-sonnet-4-6` | Anthropic model to use |
| `MAX_AGENT_ITERATIONS` | 40 | Max tool-use turns before the loop stops |
| `DEFAULT_LIMIT` | 15 | Default number of patches to fetch |
| `DEFAULT_DAYS_BACK` | 1 | Default history window in days |
| `MAX_DIFF_CHARS` | 8000 | Characters of diff sent to Claude per patch |
| `REQUEST_TIMEOUT` | 30 | HTTP timeout for Patchwork API requests (seconds) |

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key (`sk-ant-…`) |

Set via a `.env` file in the project root (loaded automatically by `python-dotenv`).

## Dependencies

| Package | Purpose |
|---------|---------|
| `anthropic` | Claude API client and tool-use support |
| `requests` | Patchwork REST API HTTP client |
| `python-dotenv` | `.env` file loading |
| `rich` | Terminal formatting (progress spinner, tables, panels) |
| `jinja2` | HTML report templating |
| `python-dateutil` | Date parsing utilities |

## Common Patchwork project names

Run `python main.py --list-projects` for the full list. Common ones:

| `--project` value | Subsystem |
|-------------------|-----------|
| `linux-usb` | USB |
| `netdev` | Networking (net-next) |
| `dri-devel` | DRM / GPU |
| `intel-gfx` | Intel i915 / Xe |
| `linux-scsi` | SCSI |
| `linux-mm` | Memory management |
| `linux-pm` | Power management |
| `linux-crypto` | Crypto |
| `linux-hwmon` | Hardware monitoring |
| `linux-iio` | Industrial I/O |
| `linux-input` | Input devices |
| `linux-media` | V4L2 / media |
