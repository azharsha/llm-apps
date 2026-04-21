# SPEC — Phase 7.1.0: Reporter + CLI Hardening
## SoCTriage v7.1.0 · Final Phase · JSON · Markdown · HTML · Argparse · Exit Codes

---

## PRD v1.1.0 vs. Reality: Four Remaining Discrepancies

### R-1: `providers/__init__.py` import paths are wrong
PRD §7 imports from `soctriage.providers.intel_provider` — module does not exist.
Actual package layout:
```
soctriage/providers/intel/provider.py    → IntelProvider
soctriage/providers/qualcomm/provider.py → QualcommProvider
soctriage/providers/amd/provider.py      → AMDProvider
soctriage/providers/nvidia/provider.py   → NVIDIAProvider
soctriage/providers/generic/provider.py  → GenericProvider
```
**Fix:** Import from `soctriage.providers.<vendor>.provider`.

### R-2: `get_provider()` calls `p.detect(token_stream)` — wrong signature
PRD §7 shows `p.detect(token_stream: list[dict])`. `SoCProvider.detect()` takes
`raw_log: str`. The existing CLI already builds `head_text = "\n".join(head_buf)` for
this purpose.

**Fix:** `get_provider(raw_log: str) -> SoCProvider` — accept a string.
The CLI passes `head_text` (same as before). Remove the PRD's `get_provider()` from
`providers/__init__.py`; only add `get_all_providers()` there (that's the only missing
symbol). Provider selection in CLI stays with `ProviderRegistry.detect_provider()`.

### R-3: `build_parser()` vs `_build_parser()` — existing tests call `build_parser()`
The existing `cli.py` exports `build_parser()` (public). PRD §8.1 shows `_build_parser()`
(private). Tests or external code may call the public name.

**Fix:** Add the new arguments to the existing `build_parser()` directly (it's additive).
No rename. The PRD's `_build_parser()` pseudocode is the implementation guide, not the
actual function name to use.

### R-4: `main()` return type change — existing entry point returns `None`
The existing `main()` returns `None` and calls `sys.exit()` internally. PRD §8.2 shows
`main(argv=None) -> int` returning exit codes.

**Fix:** Change `main()` to accept optional `argv` and return `int`. Update
`if __name__ == "__main__": sys.exit(main())`. The `[project.scripts]` entry point
handles `sys.exit(main() or 0)` automatically.

### R-5: `get_hardware_context()` accessor cannot go in hardware_decode.py (locked)
PRD §9 suggests adding accessor to `hardware_decode.py` but that file is locked.

**Fix:** Use `event.__dict__.get("hardware_context")` directly in reporter.py with
`# type: ignore[attr-defined]`. No modification to hardware_decode.py.

---

## 1. Files Changed

| File | Action | Notes |
|---|---|---|
| `soctriage/core/reporter.py` | Additive | Add `report()`, `_to_json()`, `_to_markdown()`, `OUTPUTSCHEMA`, helpers |
| `soctriage/core/html_renderer.py` | New | `render_html()` — stdlib only |
| `soctriage/cli.py` | Additive | New flags in `build_parser()`, new `main()` signature, new constants |
| `soctriage/providers/__init__.py` | Additive | `get_all_providers()` only |
| `tests/test_reporter.py` | New | 30 tests |
| `tests/test_html_renderer.py` | New | 12 tests |
| `tests/test_cli.py` | New | 20 tests |
| `tests/test_pipeline_e2e.py` | New | 18 tests |
| `tests/fixtures/phase7/` | New | 6 fixture logs |

**Do NOT modify:** assembler.py, cascade.py, classifier.py, hardware_decode.py,
agent.py, agent_result.py, tool_registry.py, llm_client.py, prompts.py,
scan_dump_parser.py, any provider file, any token_rules/*.yaml.

---

## 2. `reporter.py` — Additions

Keep all existing code. Append below it:

```python
# ── Phase 7 additions ────────────────────────────────────────────────────────

from soctriage.core.agent_result import AgentResult, ToolCall
from soctriage.core.assembler    import LogEvent

OUTPUTSCHEMA = {
    "version": str, "soctriage_version": str, "provider": str,
    "chip_gen": str, "arch": str, "kernel_ver": str, "severity": str,
    "events": list, "cascade": dict, "ascii_diagram": str,
    "root_cause": str, "fix": list, "known_issues": list,
    "confidence": float, "llm_backend": str, "llm_model": str,
    "tool_trace": list, "hardware": list, "analysis_ms": int,
}


def report(
    agent_result: AgentResult,
    *,
    fmt:         str        = "json",
    output:      str | None = None,
    pretty:      bool       = True,
    include_raw: bool       = False,
) -> str:
    try:
        if fmt == "markdown":
            rendered = _to_markdown(agent_result)
        elif fmt == "html":
            from soctriage.core.html_renderer import render_html
            rendered = render_html(agent_result)
        else:   # "json" + any unknown fmt → json
            rendered = _to_json(agent_result, pretty=pretty, include_raw=include_raw)

        if output:
            with open(output, "w", encoding="utf-8") as fh:
                fh.write(rendered)
        return rendered

    except Exception as exc:
        import json as _json
        return _json.dumps({"error": str(exc), "version": "1.0"}, indent=2)


def _to_json(result: AgentResult, pretty: bool, include_raw: bool) -> str:
    import json, importlib.metadata
    try:
        soctriage_ver = importlib.metadata.version("soctriage")
    except importlib.metadata.PackageNotFoundError:
        soctriage_ver = "dev"

    cascade = result.cascade
    doc = {
        "version":           "1.0",
        "soctriage_version": soctriage_ver,
        "provider":          cascade.events[0].provider_name if cascade.events else "generic",
        "chip_gen":          cascade.chip_gen,
        "arch":              cascade.arch,
        "kernel_ver":        cascade.kernel_ver or "unknown",
        "severity":          cascade.severity,
        "events":            [_event_to_dict(e, include_raw) for e in cascade.events],
        "cascade":           cascade.to_dict(),
        "ascii_diagram":     cascade.ascii_diagram,
        "root_cause":        result.root_cause_narrative,
        "fix":               result.fix_suggestions,
        "known_issues":      result.known_issues_matched,
        "confidence":        round(result.confidence, 4),
        "llm_backend":       result.llm_backend,
        "llm_model":         result.llm_model,
        "tool_trace":        [_tool_call_to_dict(tc) for tc in result.tool_trace],
        "hardware": [
            hw.to_dict()
            for e in cascade.events
            for hw in [e.__dict__.get("hardware_context")]  # type: ignore[attr-defined]
            if hw is not None
        ],
        "analysis_ms": result.total_ms,
    }
    return json.dumps(doc, indent=2 if pretty else None, default=str)


def _to_markdown(result: AgentResult) -> str:
    cascade = result.cascade
    lines = [
        "# SoCTriage Report",
        "",
        f"**chip_gen:** `{cascade.chip_gen}` | "
        f"**arch:** `{cascade.arch}` | "
        f"**kernel:** `{cascade.kernel_ver or 'unknown'}`",
        f"**Severity:** `{cascade.severity.upper()}`",
        "",
        "---",
        "",
        result.to_markdown(),
    ]
    return "\n".join(lines)


def _event_to_dict(event: LogEvent, include_raw: bool) -> dict:
    d: dict = {
        "event_id":   event.event_id,
        "event_type": event.event_type,
        "subsystem":  event.subsystem,
        "ip_block":   event.ip_block,
        "severity":   event.severity,
        "confidence": round(event.confidence, 4),
        "start_line": event.start_line,
        "end_line":   event.end_line,
        "chip_gen":   event.chip_gen,
        "arch":       event.arch,
    }
    if include_raw:
        d["raw_text"] = event.raw_text
    return d


def _tool_call_to_dict(tc: ToolCall) -> dict:
    return {
        "index":       tc.call_index,
        "tool":        tc.tool_name,
        "args":        tc.arguments,
        "duration_ms": tc.duration_ms,
    }
```

---

## 3. `html_renderer.py` — New File (stdlib only)

No external imports. Inline CSS. All sections built with string operations.

```python
_SEVERITY_COLOURS = {
    "critical": "#D32F2F",
    "error":    "#E64A19",
    "warning":  "#F57C00",
    "info":     "#1976D2",
}

def render_html(result: AgentResult) -> str:
    colour = _SEVERITY_COLOURS.get(result.cascade.severity, "#1976D2")
    # Builds full <!DOCTYPE html> document with:
    # - <meta charset="UTF-8"> + inline <style>
    # - <header> severity badge (background=colour)
    # - <div class="root-cause"> for root_cause_narrative
    # - <pre style="font-family:monospace"> for ascii_diagram
    # - <ol> for fix_suggestions
    # - <div class="issue-card"> per known issue
    # - <table> for events (event_id, type, subsystem, ip_block, severity, conf, lines)
    # - <table> for hardware contexts (register name, raw_value, decoded_fields)
    # - <details><summary>Tool Trace (N calls)</summary>...</details>
    # - <footer> with soctriage_version, analysis_ms, llm_backend, llm_model
```

Key constraints:
- Zero `http://` or `https://` URLs in output (no external CDN)
- `"<!DOCTYPE html>"` must be first line
- Severity badge uses inline `style="background-color: {colour}"` 
- ASCII diagram in `<pre style="font-family: monospace; white-space: pre">`

---

## 4. `providers/__init__.py` — Additive Only

```python
# providers/__init__.py — additive only (R-1 fix: correct import paths)
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soctriage.core.soc_provider import SoCProvider


def get_all_providers() -> list:
    """Return one instance of every registered provider (R-6 fix)."""
    from soctriage.core.provider_registry import ProviderRegistry
    from pathlib import Path
    reg = ProviderRegistry()
    reg.auto_discover(Path(__file__).parent)
    return reg._providers
```

Use `ProviderRegistry.auto_discover()` — avoids hardcoding class names, consistent with
existing CLI code. Returns all 5 providers in priority order.

---

## 5. `cli.py` — Additive Modifications

### 5.1 New constants (D-4 fix)
```python
# Phase 7 semantic aliases — existing EXIT_SUCCESS etc. unchanged
EXITOK       = EXIT_SUCCESS   # 0
EXITCRITICAL = 1
EXITERROR    = 2
EXITUSAGE    = 3
```

Note: existing cli.py has `EXIT_SUCCESS=0, EXIT_NO_ANOMALY=1, EXIT_PARSE_ERR=2,
EXIT_INPUT_ERR=3`. New aliases added AFTER existing constants.

### 5.2 New args added to `build_parser()` (D-3 / D-5 fix)
Append to the existing `build_parser()` function before `return p`:

```python
# Phase 7 additions — positional LOG_FILE (D-5)
p.add_argument("log_file", nargs="?", default=None, metavar="LOG_FILE",
               help="Kernel log file (.log .gz .bz2 .xz) or - for stdin")

# Update existing --format to include html
# (find the existing --format argument and update choices to ["json","markdown","html"])

# New LLM flags
p.add_argument("--no-llm", action="store_true",
               help="Skip LLM agent — Phase 4 cascade result only")
p.add_argument("--llm-backend", choices=["anthropic", "ollama"], default="anthropic")
p.add_argument("--llm-model", default="claude-sonnet-4-5", metavar="MODEL")
p.add_argument("--ollama-host", default="http://localhost:11434", metavar="URL")
p.add_argument("--timeout", type=int, default=60, metavar="SECS")
p.add_argument("--include-raw", action="store_true",
               help="Include raw event text in JSON output")

# Utility
p.add_argument("--version", action="store_true",
               help="Show soctriage version and exit")
```

The existing `--format choices=["json","markdown","both"]` must be updated to
`choices=["json","markdown","html"]` (replace "both" with "html"). This is a breaking
change to the "both" option — acceptable as the pipeline now uses `report()` not
`render_json + render_markdown`.

### 5.3 Updated `main()` (D-4, full pipeline)

Replace the existing `main() -> None` with `main(argv=None) -> int`. Key changes:
- `args = build_parser().parse_args(argv)` (accepts injected args for tests)
- Handle `--version` and `--list-providers` early exits using `get_all_providers()`
- Resolve `log_path = args.log_file or args.input` (D-5 positional fallback)
- Add Phase 3c `decode_hardware()` call between Phase 3 and Phase 4
- Add Phase 6 `run_agent()` call after Phase 4
- Replace `render_json/render_markdown` calls with `report(agent_result, ...)`
- Return `_exit_code(agent_result)` integer; `if __name__ == "__main__": sys.exit(main())`
- Keep `--plugin`, `--token-rule`, `--asic-gen`, `--soc-provider` existing args intact

### 5.4 New helper functions

```python
def _exit_code(result: AgentResult) -> int:
    if result.cascade.severity == "critical":
        return EXITCRITICAL
    return EXITOK

def _vlog(verbose: bool, msg: str) -> None:
    if verbose:
        import time
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr)
```

---

## 6. Fixture Logs — `tests/fixtures/phase7/`

Small synthetic logs (< 30 lines) generated in `conftest.py` using `tmp_path` or
written as static files. Content must be enough for provider detection:

| File | Key lines |
|---|---|
| `amd_mi300_critical.log` | `amdgpu`, `firmware_fail`, `GPU HANG`, `BUG:` |
| `intel_dg2_error.log` | `i915`, `GuC`, `GPU HANG` |
| `qcom_adsp_critical.log` | `qcom`, `ADSP crash`, `BUG:` |
| `nvidia_gsp_error.log` | `nvidia`, `GSP firmware`, `XID 79` |
| `generic_empty.log` | (empty — 0 bytes) |
| `generic_nocrash.log` | generic kernel info lines, no error keywords |

---

## 7. Critical Implementation Details

### 7.1 `report()` error fallback
The outer `try/except` in `report()` catches render errors and returns minimal JSON:
```python
{"error": "...", "version": "1.0"}
```
This satisfies `test_report_never_raises_on_empty_result`.

### 7.2 `OUTPUTSCHEMA` conformance
`test_no_extra_keys_outside_schema` checks that no keys outside `OUTPUTSCHEMA` appear in
the JSON output. The `_to_json()` output has exactly the 19 keys in `OUTPUTSCHEMA`.

### 7.3 HTML no-external-deps test
`test_html_no_external_dependencies` asserts that neither `"http://"` nor `"https://"`
appears in the rendered HTML string.

### 7.4 `test_xfail06_report_stub_now_passes`
This is just a normal passing test — there is no actual `@pytest.mark.xfail` in
`test_scaffold.py` for `report()`. The test simply calls `report(agent_result)` and
asserts it doesn't raise and returns a string. It documents that the Phase 0 stub
intention is now fulfilled.

### 7.5 `test_e2e_gz_compressed_log_no_llm`
Creates a `.gz` compressed version of `amd_mi300_critical.log` in the test and passes it
to the pipeline. Phase 1's `open_log()` handles decompression.

### 7.6 CLI tests use `main(argv=[...])` pattern
Tests call `main(["path/to/log", "--no-llm", "--format", "json"])` directly, checking
the returned integer exit code. No `subprocess` needed.

### 7.7 mypy for `html_renderer.py` and `reporter.py`
`# type: ignore[attr-defined]` on `event.__dict__.get("hardware_context")` lines.
`html_renderer.py` imports only from stdlib and `agent_result.py` — no untyped deps.

---

## 8. Acceptance Criteria

| Source | Count |
|---|---|
| `test_reporter.py` | 30 |
| `test_html_renderer.py` | 12 |
| `test_cli.py` | 20 |
| `test_pipeline_e2e.py` | 18 |
| **Total** | **80** |

Combined suite gate: **~1048 passed · 0 xfailed · 0 failed**
mypy 0 errors on `soctriage/` package. Coverage ≥ 85% on Phase 7 files.
