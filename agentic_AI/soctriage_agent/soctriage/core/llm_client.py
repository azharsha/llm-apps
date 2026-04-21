"""
llm_client.py — Phase 6 v6.0.0

LLM client abstraction for the SoCTriage agent loop.
Supports OpenAI (GPT-4o) and Ollama (local) backends.

openai and httpx are imported LAZILY inside __init__ / chat() so that
the base soctriage install works without them.

Public symbols: LLMClient, OpenAIClient, OllamaClient, LLMResponse, ToolCallRequest
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

__all__ = [
    "LLMClient", "OpenAIClient", "OllamaClient",
    "LLMResponse", "ToolCallRequest",
]


@dataclass
class ToolCallRequest:
    id:        str
    tool_name: str
    arguments: dict


@dataclass
class LLMResponse:
    content:     str | None
    tool_calls:  list[ToolCallRequest]
    stop_reason: str    # "stop" | "tool_calls" | "length" | "error"
    usage:       dict


class LLMClient(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools:    list,
        *,
        temperature: float = 0.1,
        max_tokens:  int   = 2048,
    ) -> LLMResponse: ...


class OpenAIClient(LLMClient):
    """
    Uses openai>=1.0.0 SDK.
    Reads OPENAI_API_KEY from environment.
    Default model: gpt-4o (configurable via --llm-model flag).

    openai is imported inside __init__ so the base install works without it.
    """

    def __init__(self, model: str = "gpt-4o", base_url: str | None = None):
        try:
            import openai
        except ImportError:
            raise ImportError(
                "openai package required: pip install soctriage[llm]"
            )
        self._client = openai.OpenAI(base_url=base_url)
        self._model  = model

    def chat(
        self,
        messages: list[dict],
        tools:    list,
        *,
        temperature: float = 0.1,
        max_tokens:  int   = 2048,
    ) -> LLMResponse:
        import json
        response = self._client.chat.completions.create(
            model       = self._model,
            messages    = messages,
            tools       = [t.to_openai_schema() for t in tools],
            temperature = temperature,
            max_tokens  = max_tokens,
        )
        choice = response.choices[0]
        tool_calls: list[ToolCallRequest] = []
        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(ToolCallRequest(
                    id        = tc.id,
                    tool_name = tc.function.name,
                    arguments = json.loads(tc.function.arguments),
                ))
        return LLMResponse(
            content     = choice.message.content,
            tool_calls  = tool_calls,
            stop_reason = choice.finish_reason or "stop",
            usage       = response.usage.model_dump() if response.usage else {},
        )


class OllamaClient(LLMClient):
    """
    Uses Ollama REST API at http://localhost:11434.
    Supports any model with tool-calling: llama3, mistral-nemo, deepseek-coder-v2.

    httpx is imported inside chat() so the base install works without it.
    httpx.ConnectError propagates to the agent loop → _fallback_agent_result.
    """

    def __init__(
        self,
        model: str = "llama3:8b",
        host:  str = "http://localhost:11434",
    ):
        self._model = model
        self._host  = host

    def chat(
        self,
        messages: list[dict],
        tools:    list,
        *,
        temperature: float = 0.1,
        max_tokens:  int   = 2048,
    ) -> LLMResponse:
        try:
            import httpx
        except ImportError:
            raise ImportError(
                "httpx package required: pip install soctriage[llm]"
            )
        import json
        payload = {
            "model":    self._model,
            "messages": messages,
            "tools":    [t.to_openai_schema() for t in tools],
            "options":  {"temperature": temperature, "num_predict": max_tokens},
            "stream":   False,
        }
        resp = httpx.post(f"{self._host}/api/chat", json=payload, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
        msg  = data["message"]
        tool_calls: list[ToolCallRequest] = []
        for tc in msg.get("tool_calls", []):
            tool_calls.append(ToolCallRequest(
                id        = tc.get("id", ""),
                tool_name = tc["function"]["name"],
                arguments = tc["function"].get("arguments", {}),
            ))
        return LLMResponse(
            content     = msg.get("content"),
            tool_calls  = tool_calls,
            stop_reason = "tool_calls" if tool_calls else "stop",
            usage       = {},
        )
