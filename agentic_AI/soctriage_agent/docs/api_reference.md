# SoCTriage — Python API Reference

SoCTriage exposes a public Python API for embedding in other tools.

## `open_log(path: str) -> tuple[Iterator[str], InputMeta]`

```python
from soctriage.core.input_handler import open_log

lines, meta = open_log("/var/log/dmesg")
# or: lines, meta = open_log("crash.log.gz")  # auto-decompressed
# or: lines, meta = open_log("-")              # stdin
```

`InputMeta` fields: `source_path`, `size_bytes`, `compression`, `container_hint`.

Raises `FileNotFoundError` or `InputError` on failure.

---

## `tokenize(lines, *, chip_gen_hint=None, rule_registry=None) -> list[LogToken]`

```python
from soctriage.core.tokenizer  import tokenize
from soctriage.core.token_rule import TokenRuleRegistry

registry = TokenRuleRegistry()
registry.load_defaults()

tokens = tokenize(lines, rule_registry=registry)
```

`LogToken` fields: `token_type`, `line_no`, `raw_text`, `arch`, `chip_gen`,
`confidence`, `timestamp`, `is_duplicate`.

---

## `assemble(tokens, *, provider=None) -> Iterator[LogEvent]`

```python
from soctriage.core.assembler import assemble

events = list(assemble(iter(tokens), provider=provider))
```

Groups related tokens into `LogEvent` objects.

---

## `classify_all(events, *, provider=None) -> Iterator[LogEvent]`

```python
from soctriage.core.classifier import classify_all

events = list(classify_all(raw_events, provider=provider))
```

Assigns `subsystem`, `ip_block`, `severity`, and final `confidence` to each event.

---

## `decode_hardware(events, *, provider=None) -> list[LogEvent]`

```python
from soctriage.core.hardware_decode import decode_hardware

events = decode_hardware(events, provider=provider)
# Each event may now have event.__dict__["hardware_context"] attached
```

---

## `analyse(events, *, max_edges=500, min_confidence=0.15) -> CascadeResult`

```python
from soctriage.core.cascade import analyse

result = analyse(events)
```

`CascadeResult` fields: `events`, `edges`, `root_cause_id`, `root_cause_conf`,
`severity`, `chip_gen`, `arch`, `kernel_ver`, `event_count`, `critical_count`,
`error_count`, `analysis_ns`, `ascii_diagram`, `subsystems_hit`.

---

## `run_agent(cascade, *, provider, backend, model, ollama_host, no_llm) -> AgentResult`

```python
from soctriage.core.agent import run_agent

agent_result = run_agent(
    cascade,
    provider=provider,
    backend="anthropic",        # or "ollama"
    model="claude-sonnet-4-5",
    ollama_host="http://localhost:11434",
    no_llm=False,
)
```

`AgentResult` fields: `cascade`, `root_cause_narrative`, `fix_suggestions`,
`known_issues_matched`, `confidence`, `llm_backend`, `llm_model`, `tool_trace`,
`total_ms`.

---

## `report(agent_result, *, fmt="json", output=None, pretty=True, include_raw=False) -> str`

```python
from soctriage.core.reporter import report

json_str = report(agent_result, fmt="json")
md_str   = report(agent_result, fmt="markdown")
html_str = report(agent_result, fmt="html")

# Write to file
report(agent_result, fmt="html", output="report.html")
```

Never raises — returns `{"error": "...", "version": "1.0"}` JSON on failure.

---

## Full pipeline example

```python
from soctriage.core.input_handler  import open_log
from soctriage.core.token_rule     import TokenRuleRegistry
from soctriage.core.tokenizer      import tokenize
from soctriage.core.assembler      import assemble
from soctriage.core.classifier     import classify_all
from soctriage.core.hardware_decode import decode_hardware
from soctriage.core.cascade        import analyse
from soctriage.core.agent          import run_agent
from soctriage.core.reporter       import report
from soctriage.core.provider_registry import ProviderRegistry
from pathlib import Path

registry = TokenRuleRegistry()
registry.load_defaults()

provider_reg = ProviderRegistry()
provider_reg.auto_discover(Path("soctriage/providers"))

lines, meta = open_log("crash.log")
head = []
for i, line in enumerate(lines):
    head.append(line)
    if i >= 499:
        break

import itertools
all_lines = itertools.chain(iter(head), lines)
provider  = provider_reg.detect_provider("\n".join(head))
tokens    = tokenize(all_lines, rule_registry=registry)
events    = list(classify_all(assemble(iter(tokens), provider=provider), provider=provider))
events    = decode_hardware(events, provider=provider)
cascade   = analyse(events)

agent_result = run_agent(cascade, provider=provider, backend="anthropic",
                          model="claude-sonnet-4-5", ollama_host="", no_llm=True)
print(report(agent_result, fmt="json"))
```
