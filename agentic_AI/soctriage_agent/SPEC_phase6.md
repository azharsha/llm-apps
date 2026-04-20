# SPEC — Phase 6: Agentic AI Layer
## SoCTriage v6.0.0 · LLM Agent Loop · Tool Registry · Offline Mode

---

## ⚠️ PRD vs. Reality: Five Discrepancies

### D-1: Existing stub is `core/llm_agent.py`, not the 5 files PRD names

The PRD defines: `agent.py`, `tool_registry.py`, `agent_result.py`, `llm_client.py`, `prompts.py`.
The codebase has one stub: `soctriage/core/llm_agent.py` (1 line docstring).

**Decision:** Create the 5 PRD-named files. Delete (or keep empty) `llm_agent.py` — it is
a stub and contains no logic. Keep it as a re-export shim pointing to `agent.py` so no
import that currently succeeds breaks.

### D-2: Stub docstring says "Anthropic Claude" — PRD says "OpenAI + Ollama"

`llm_agent.py:1` reads: _"Anthropic Claude RCA narrative with tool-calling agent loop."_
The PRD specifies GPT-4o and Ollama as the two backends.

**Decision:** Implement the PRD backends (OpenAI + Ollama). Add a note that a future
`AnthropicClient` is a drop-in via the `LLMClient` ABC — the stub docstring was aspirational.
The `claude-api` skill should be used if/when the Anthropic backend is added.

### D-3: `_get_known_issues` calls `provider.match_known_issues()` — method does not exist

The PRD snippet (§4.2) calls `ctx.provider.match_known_issues(chip_gen, event_types)`.
The actual `SoCProvider` interface (`soc_provider.py`) has `get_known_issues(chip_gen, event_types)`.

**Fix:** Use `provider.get_known_issues(chip_gen, event_types)` — exact name from the interface.

### D-4: Suite baseline is 888 passed (not ~682 as PRD states)

The PRD says "Depends On: Phase 5 DONE (~682 PASSED)". After Phase 3c the actual count is
888 passed · 6 xfailed. Combined gate after Phase 6 is therefore **~963 passed** (not ~757).

### D-5: `get_severity_summary` tool recomputes `warning` incorrectly

PRD §4.1 computes `warning = total - critical - error`, discarding `info_count`.
`CascadeResult` already has `warning_count` and `info_count` fields. Use them directly.

---

## 1. Objective

Wrap the Phase 4 `CascadeResult` in an autonomous tool-calling agent loop that produces
a structured `AgentResult` with root-cause narrative, fix suggestions, and known-issues
matching. All LLM calls mocked in CI. LLM is optional — `no_llm=True` returns a valid
fallback result from Phase 4 data alone.

---

## 2. New Files

| File | Role |
|---|---|
| `soctriage/core/agent_result.py` | `ToolCall`, `AgentResult` dataclasses |
| `soctriage/core/tool_registry.py` | `Tool`, `AgentContext`, `ToolRegistry` (10 tools) |
| `soctriage/core/llm_client.py` | `LLMClient` ABC, `OpenAIClient`, `OllamaClient`, `LLMResponse`, `ToolCallRequest` |
| `soctriage/core/prompts.py` | `SYSTEM_PROMPT`, `USER_PROMPT` templates, `_build_system_message()` |
| `soctriage/core/agent.py` | `SoCTriageAgent`, `run_agent()`, `_fallback_agent_result()`, `_parse_agent_result()` |
| `soctriage/core/llm_agent.py` | Re-export shim: `from soctriage.core.agent import run_agent` |

**Do NOT modify:** assembler.py, classifier.py, cascade.py, soc_provider.py, cli.py,
reporter.py, tokenizer.py, token_rule.py, any token_rules/*.yaml, any provider file.

---

## 3. `agent_result.py`

```python
@dataclass
class ToolCall:
    tool_name:   str
    arguments:   dict
    response:    dict
    duration_ms: int
    call_index:  int   # 1-based within this agent run

@dataclass
class AgentResult:
    cascade:                CascadeResult
    root_cause_narrative:   str
    fix_suggestions:        list[str]
    known_issues_matched:   list[dict]
    confidence:             float        # 0.0–1.0
    subsystem_narrative:    str
    tool_trace:             list[ToolCall]
    llm_backend:            str          # "openai" | "ollama" | "none"
    llm_model:              str
    iterations:             int
    total_ms:               int
    offline_mode:           bool
    no_llm_mode:            bool

    def to_dict(self) -> dict: ...       # JSON-serialisable
    def to_markdown(self) -> str: ...    # consumed by Phase 7 reporter
```

`to_dict()` must be JSON-serialisable (no dataclass nesting — convert `cascade` via
`cascade.to_dict()`). `to_markdown()` per PRD §8.

---

## 4. `tool_registry.py`

### 4.1 `AgentContext`

```python
@dataclass
class AgentContext:
    cascade:  CascadeResult
    provider: SoCProvider | None = None
```

### 4.2 `Tool`

```python
@dataclass
class Tool:
    name:        str
    description: str
    parameters:  dict           # JSON Schema "properties" dict
    fn:          Callable       # fn(ctx, **kwargs) -> dict | list | str
    
    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": list(self.parameters.keys()),
                },
            },
        }
```

### 4.3 The 10 Tools

| # | Name | Args | Returns |
|---|---|---|---|
| 1 | `get_root_cause` | — | `cascade.to_dict()["root_cause"]` |
| 2 | `get_cascade_chain` | — | `cascade.to_dict()["cascade"]` |
| 3 | `get_ascii_diagram` | — | `cascade.ascii_diagram` (str) |
| 4 | `get_event_detail` | `event_id: int` | event fields + `raw_text[:800]` |
| 5 | `get_known_issues` | — | `provider.get_known_issues(chip_gen, event_types)` — **not** `match_known_issues` |
| 6 | `get_subsystem_events` | `subsystem: str` | events where `e.subsystem == subsystem` |
| 7 | `get_provider_info` | — | provider_name, chip_gen, arch, kernel_ver |
| 8 | `get_ip_blocks` | — | unique ip_blocks (excluding `"unknown"`) |
| 9 | `get_severity_summary` | — | use `cascade.warning_count`, `cascade.info_count` directly (not recomputed) |
| 10 | `get_call_trace` | `event_id: int` | call_trace_frame tokens for that event |

### 4.4 `ToolRegistry`

```python
class ToolRegistry:
    def all_tools(self) -> list[Tool]: ...
    def execute(self, tool_name: str, arguments: dict, ctx: AgentContext) -> dict:
        """Returns error dict on unknown tool — never raises."""
```

---

## 5. `llm_client.py`

```python
class LLMClient(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], tools: list[Tool], *,
             temperature: float = 0.1, max_tokens: int = 2048) -> LLMResponse: ...

@dataclass
class LLMResponse:
    content:     str | None
    tool_calls:  list[ToolCallRequest]
    stop_reason: str    # "stop" | "tool_calls" | "length" | "error"
    usage:       dict

@dataclass
class ToolCallRequest:
    id:        str
    tool_name: str
    arguments: dict
```

**OpenAIClient:** `openai>=1.0.0`, reads `OPENAI_API_KEY` env var, default model `gpt-4o`.
Import `openai` inside `__init__` (optional dep — `ImportError` → clear message).

**OllamaClient:** `httpx>=0.27.0`, default `http://localhost:11434`, 60s timeout.
Import `httpx` inside `chat()`. `ConnectError` must propagate so the agent loop
catches it and returns `_fallback_agent_result`.

---

## 6. `prompts.py`

`SYSTEM_PROMPT`: format string with `{chip_gen}`, `{arch}`, `{kernel_ver}`,
`{provider}`, `{subsystems_hit}`. Exactly 8 rules from PRD §5.1.

`USER_PROMPT`: static string from PRD §5.1.

```python
def _build_system_message(cascade: CascadeResult) -> dict:
    return {
        "role": "system",
        "content": SYSTEM_PROMPT.format(
            chip_gen      = cascade.chip_gen,
            arch          = cascade.arch,
            kernel_ver    = cascade.kernel_ver or "unknown",
            provider      = cascade.events[0].provider_name if cascade.events else "generic",
            subsystems_hit= ", ".join(cascade.subsystems_hit),
        ),
    }
```

---

## 7. `agent.py` — Agent Loop

```python
class SoCTriageAgent:
    MAX_ITERATIONS = 8

    def run(self, cascade: CascadeResult) -> AgentResult:
        # Never raises — all exceptions caught → _fallback_agent_result
```

**Loop protocol (per PRD §7):**
1. Build `[system_msg, user_msg]`
2. `resp = llm.chat(messages, registry.all_tools())`
3. `stop_reason == "tool_calls"` → execute each tool, append `assistant` + `tool` messages, continue
4. `stop_reason == "stop"` + content → `_parse_agent_result()`, break
5. Other stop reason (length/error) → break with partial result
6. `iterations >= MAX_ITERATIONS` → break

**Tool message format** (OpenAI-compatible):
```python
# assistant turn
messages.append({"role": "assistant", "tool_calls": [
    {"id": tc.id, "type": "function",
     "function": {"name": tc.tool_name, "arguments": json.dumps(tc.arguments)}}
    for tc in resp.tool_calls
]})
# tool results
for tc in resp.tool_calls:
    messages.append({"role": "tool", "tool_call_id": tc.id,
                     "content": json.dumps(result)})
```

**`_parse_agent_result(text, cascade, tool_trace, iterations, total_ms)`:**
Parse `final_text` (LLM's final JSON or free-text response) into `AgentResult` fields.
The LLM is instructed to respond with JSON containing `root_cause_narrative`,
`fix_suggestions`, `confidence`, `subsystem_narrative`. Use `json.loads()` with
fallback to treating the whole text as `root_cause_narrative`.

**`_fallback_agent_result(cascade, error="")`:** per PRD §7.1 exactly.

**`run_agent()` entry point:** per PRD §12.

---

## 8. Fixture Files — `tests/fixtures/phase6/`

6 JSON files. Each is a minimal valid `CascadeResult.to_dict()` output plus a
`_mock_llm_responses` key (list of mocked `LLMResponse`-like dicts for tests).

| File | cascade summary |
|---|---|
| `intel_dg2_guc.json` | firmware_fail → gpu_hang, root_cause_conf ~0.85 |
| `amd_mi300_mmhub.json` | memory_fault → gpu_hang → kernel_panic |
| `qcom_adsp_panic.json` | soc_crash → kernel_panic |
| `nvidia_gsp_timeout.json` | firmware_fail → gpu_hang |
| `generic_unknown.json` | single unknown_event, no provider |
| `empty_cascade.json` | events=[], root_cause_id=None |

Construct these programmatically in test helpers rather than large static JSON blobs.

---

## 9. Test Files — 75 Tests Total

| File | Count | Notes |
|---|---|---|
| `tests/test_agent.py` | 30 | All LLM calls mocked via `unittest.mock.patch` |
| `tests/test_tool_registry.py` | 20 | Pure function calls, no LLM |
| `tests/test_llm_client.py` | 15 | Mock `openai.OpenAI` and `httpx.post` |
| `tests/test_agent_result.py` | 10 | Dataclass + serialisation |

All tests in CI must pass with `OPENAI_API_KEY=mock-key-for-ci` and no live network.

**Critical tests to get right:**
- `test_ec30_max_iterations_enforced` — mock LLM always returns tool_calls; assert loop stops at 8
- `test_ec31_unknown_tool_name_no_crash` — registry.execute returns `{"error": "..."}`, loop continues
- `test_ec28_llm_timeout_fallback` — mock LLM raises `Exception`; fallback result returned, `no_llm_mode=True`
- `test_full_pipeline_open_log_to_agent_result` — end-to-end with mocked LLM

---

## 10. `pyproject.toml`

Add optional dependency group:
```toml
[project.optional-dependencies]
llm = [
    "openai>=1.0.0",
    "httpx>=0.27.0",
]
```
Base `pip install soctriage` must succeed without `openai` or `httpx` installed.
Verify: importing `soctriage.core.agent_result` and `soctriage.core.tool_registry`
must NOT import `openai` or `httpx` at module level.

---

## 11. Acceptance Criteria Summary

| Source | Count |
|---|---|
| `test_agent.py` | 30 |
| `test_tool_registry.py` | 20 |
| `test_llm_client.py` | 15 |
| `test_agent_result.py` | 10 |
| **Total** | **75** |

Combined suite gate: **~963 passed · 6 xfailed · 0 failed**

---

## 12. Definition of Done

- [ ] 75 Phase 6 tests pass (mocked LLM, no live network)
- [ ] mypy 0 errors across all 5 Phase 6 files
- [ ] Coverage ≥ 85% on agent.py, tool_registry.py, llm_client.py, agent_result.py
- [ ] All 8 edge cases EC-28–EC-35 green
- [ ] `run_agent(..., no_llm=True)` returns valid `AgentResult` with no imports of openai/httpx
- [ ] `AgentResult.to_dict()` JSON-serialisable; `to_markdown()` valid Markdown
- [ ] `pip install soctriage` succeeds without openai or httpx
- [ ] Privacy contract: LLM never receives `raw_text` directly (only `raw_text[:800]` excerpts via tool calls)
- [ ] All locked files byte-for-byte unchanged
- [ ] Full pipeline verified: `open_log → tokenize → assemble → classify_all → analyse → run_agent → to_markdown()`
