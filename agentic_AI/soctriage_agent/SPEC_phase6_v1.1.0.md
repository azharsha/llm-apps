# SPEC — Phase 6.1.0: Anthropic Claude Backend
## SoCTriage v6.1.0 · Replaces OpenAI with Anthropic · Anthropic message format

---

## PRD vs. Reality: Four Discrepancies

### D-1: PRD baseline count is wrong
PRD §16 says "~682 PASSED" inherited from Phase 5. Actual suite after Phase 6.0.0 + fixes: **967 passed · 6 xfailed**. Combined gate after this update: **~967 passed** (not ~757).

### D-2: `_build_system_prompt` vs `_build_system_message`
PRD §8 calls `_build_system_prompt(cascade)` returning a string.  
Existing `prompts.py` exports `_build_system_message(cascade)` returning a `{"role": "system", "content": ...}` dict.  
**Decision:** Keep `_build_system_message` — the dict form is more ergonomic. Agent.py extracts `system_content` from `messages` by role (PRD §5.2 approach), which works cleanly with the existing helper.

### D-3: PRD fallback uses `error=str(exc)` — security fix must be preserved
Phase 6.0.0 code review (fix commit cc5055aa) scrubbed `str(exc)` from `_fallback_agent_result` to prevent API key leakage. PRD §8.1 restores `error=str(exc)`. **Decision:** Keep the security fix — pass `error="LLM call failed"` in the except block, not `str(exc)`.

### D-4: OllamaClient tool schema
PRD §5.3 shows OllamaClient building OpenAI-format tool schemas inline. After renaming `to_openai_schema()` → `to_anthropic_schema()`, OllamaClient must build the OpenAI-compatible format itself (Ollama speaks OpenAI protocol). The `to_anthropic_schema()` method is only called by AnthropicClient.

---

## 1. What Changes (v6.0.0 → v6.1.0)

| File | Change |
|---|---|
| `soctriage/core/llm_client.py` | Replace `OpenAIClient` with `AnthropicClient`; update `OllamaClient` stop_reason strings; update `__all__` |
| `soctriage/core/tool_registry.py` | Rename `to_openai_schema()` → `to_anthropic_schema()`; update schema format |
| `soctriage/core/agent.py` | Update stop_reason checks ("tool_use"/"end_turn"); update Anthropic message format; update defaults |
| `pyproject.toml` | `openai>=1.0.0` → `anthropic>=0.25.0` |
| `mypy.ini` | `[mypy-openai]` → `[mypy-anthropic]` |
| `tests/test_llm_client.py` | Replace OpenAI mock tests with Anthropic mock tests (15 tests, same count) |
| `tests/test_agent.py` | Update mock targets; rename ec28 test; update run_agent backend default |

**Do NOT modify:** agent_result.py, prompts.py, tool functions inside tool_registry.py, assembler.py, cascade.py, classifier.py, any provider file.

---

## 2. `llm_client.py` Changes

### 2.1 Replace OpenAIClient with AnthropicClient

```python
class AnthropicClient(LLMClient):
    def __init__(self, model: str = "claude-sonnet-4-5", base_url: str | None = None):
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package required: pip install soctriage[llm]")
        self._client = anthropic.Anthropic(base_url=base_url)
        self._model  = model

    def chat(self, messages, tools, *, temperature=0.1, max_tokens=2048) -> LLMResponse:
        import anthropic
        # Separate system message — Anthropic takes system as top-level param
        system_content = None
        conversation   = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                conversation.append(msg)
        kwargs = dict(
            model=self._model, max_tokens=max_tokens,
            tools=[t.to_anthropic_schema() for t in tools],
            messages=conversation, temperature=temperature,
        )
        if system_content:
            kwargs["system"] = system_content
        response = self._client.messages.create(**kwargs)
        tool_calls = []
        text_content = None
        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCallRequest(id=block.id, tool_name=block.name, arguments=block.input))
            elif block.type == "text":
                text_content = block.text
        return LLMResponse(
            content=text_content, tool_calls=tool_calls,
            stop_reason=response.stop_reason,  # "end_turn" | "tool_use" | "max_tokens"
            usage={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        )
```

### 2.2 OllamaClient — stop_reason strings only

Change returned `stop_reason` from `"tool_calls"/"stop"` to `"tool_use"/"end_turn"` to match the unified stop_reason vocabulary. Build tools inline (OpenAI-compatible format for Ollama).

---

## 3. `tool_registry.py` Changes

Rename method only:
```python
# Before
def to_openai_schema(self) -> dict:
    return {"type": "function", "function": {"name": ..., "parameters": ...}}

# After
def to_anthropic_schema(self) -> dict:
    return {"name": ..., "description": ..., "input_schema": {"type": "object", "properties": ..., "required": [...]}}
```

---

## 4. `agent.py` Changes

### 4.1 Stop reason vocabulary
- `"tool_calls"` → `"tool_use"`  
- `"stop"` → `"end_turn"`

### 4.2 Anthropic message format
```python
# Assistant turn (tool_use blocks)
messages.append({"role": "assistant", "content": [
    {"type": "tool_use", "id": tc_req.id, "name": tc_req.tool_name, "input": tc_req.arguments}
    for tc_req in resp.tool_calls
]})
# Tool result turn (user message with tool_result blocks)
messages.append({"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": tc_req.id, "content": json.dumps(result, default=str)}
    for tc_req, result in zip(resp.tool_calls, results)
]})
```

### 4.3 Defaults
- `llm_backend` default: `"anthropic"`
- `llm_model` default: `"claude-sonnet-4-5"`
- `run_agent()` default `backend="anthropic"`, `model="claude-sonnet-4-5"`

---

## 5. Acceptance Criteria

Same 75 tests, same structure. Combined gate: **~967 passed · 6 xfailed · 0 failed**.
mypy 0 errors. Coverage ≥ 85% on Phase 6 core files.
