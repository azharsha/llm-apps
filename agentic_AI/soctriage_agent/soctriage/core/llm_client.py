"""
llm_client.py — Phase 6 v6.1.0

LLM client abstraction for the SoCTriage agent loop.
Supports Anthropic Claude (primary) and Ollama (offline fallback).

anthropic and httpx are imported LAZILY inside __init__ / chat() so that
the base soctriage install works without them.

Public symbols: LLMClient, AnthropicClient, OllamaClient, LLMResponse, ToolCallRequest
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

__all__ = [
    "LLMClient", "AnthropicClient", "OllamaClient",
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
    stop_reason: str    # "end_turn" | "tool_use" | "max_tokens" | "error"
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


class AnthropicClient(LLMClient):
    """
    Anthropic Claude backend.
    Reads ANTHROPIC_API_KEY from environment.
    Default model: claude-sonnet-4-5 (configurable via --llm-model flag).

    Supported models:
      claude-opus-4-5   — highest capability, slower
      claude-sonnet-4-5 — recommended default (best balance)
      claude-haiku-3-5  — fastest, lowest cost

    anthropic is imported inside __init__ so the base install works without it.
    """

    def __init__(self, model: str = "claude-sonnet-4-5", base_url: str | None = None):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package required: pip install soctriage[llm]"
            )
        self._client = anthropic.Anthropic(base_url=base_url)
        self._model  = model

    def chat(
        self,
        messages: list[dict],
        tools:    list,
        *,
        temperature: float = 0.1,
        max_tokens:  int   = 2048,
    ) -> LLMResponse:
        import anthropic

        # Separate system message — Anthropic takes system as a top-level param
        system_content: str | None = None
        conversation: list[dict] = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                conversation.append(msg)

        kwargs: dict = dict(
            model       = self._model,
            max_tokens  = max_tokens,
            tools       = [t.to_anthropic_schema() for t in tools],
            messages    = conversation,
            temperature = temperature,
        )
        if system_content:
            kwargs["system"] = system_content

        response = self._client.messages.create(**kwargs)

        tool_calls: list[ToolCallRequest] = []
        text_content: str | None = None

        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCallRequest(
                    id        = block.id,
                    tool_name = block.name,
                    arguments = block.input,
                ))
            elif block.type == "text":
                text_content = block.text

        return LLMResponse(
            content     = text_content,
            tool_calls  = tool_calls,
            stop_reason = response.stop_reason,  # "end_turn" | "tool_use" | "max_tokens"
            usage       = {
                "input_tokens":  response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
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

        # Ollama uses OpenAI-compatible tool format
        ollama_tools = [
            {
                "type": "function",
                "function": {
                    "name":        t.name,
                    "description": t.description,
                    "parameters": {
                        "type":       "object",
                        "properties": t.parameters,
                        "required":   list(t.parameters.keys()),
                    },
                },
            }
            for t in tools
        ]

        payload = {
            "model":    self._model,
            "messages": messages,
            "tools":    ollama_tools,
            "options":  {"temperature": temperature, "num_predict": max_tokens},
            "stream":   False,
        }
        resp = httpx.post(f"{self._host}/api/chat", json=payload, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
        msg  = data["message"]

        tool_calls: list[ToolCallRequest] = []
        for i, tc in enumerate(msg.get("tool_calls", [])):
            fn   = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            tool_calls.append(ToolCallRequest(
                id        = tc.get("id") or f"ollama_{i}",
                tool_name = fn.get("name", ""),
                arguments = args,
            ))

        return LLMResponse(
            content     = msg.get("content"),
            tool_calls  = tool_calls,
            stop_reason = "tool_use" if tool_calls else "end_turn",
            usage       = {},
        )
