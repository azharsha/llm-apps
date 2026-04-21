"""
test_llm_client.py — Phase 6 v6.1.0

15 tests for LLMClient ABC, AnthropicClient, OllamaClient.
All network calls are mocked. No live API keys required.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from soctriage.core.llm_client import (
    LLMClient, AnthropicClient, OllamaClient,
    LLMResponse, ToolCallRequest,
)
from soctriage.core.tool_registry import Tool


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_tool(name: str = "get_root_cause", params: dict | None = None) -> Tool:
    return Tool(
        name=name,
        description="Returns root cause.",
        parameters=params or {},
        fn=lambda ctx: {},
    )


def _anthropic_end_turn_response():
    """Mock Anthropic response with stop_reason='end_turn'."""
    text_block       = MagicMock()
    text_block.type  = "text"
    text_block.text  = "The root cause is a firmware failure."
    resp             = MagicMock()
    resp.content     = [text_block]
    resp.stop_reason = "end_turn"
    resp.usage       = MagicMock(input_tokens=100, output_tokens=50)
    return resp


def _anthropic_tool_use_response():
    """Mock Anthropic response with stop_reason='tool_use'."""
    tool_block        = MagicMock()
    tool_block.type   = "tool_use"
    tool_block.id     = "toolu_01"
    tool_block.name   = "get_root_cause"
    tool_block.input  = {}
    resp              = MagicMock()
    resp.content      = [tool_block]
    resp.stop_reason  = "tool_use"
    resp.usage        = MagicMock(input_tokens=80, output_tokens=20)
    return resp


def _make_anthropic_client(mock_sdk_client: MagicMock) -> AnthropicClient:
    """Create an AnthropicClient with mocked internal anthropic SDK client."""
    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_sdk_client
    mock_anthropic_module.AuthenticationError    = Exception
    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        ac = AnthropicClient(model="claude-sonnet-4-5")
    return ac


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_anthropic_client_instantiates():
    """AnthropicClient should construct without live network (mocked anthropic)."""
    mock_sdk = MagicMock()
    ac = _make_anthropic_client(mock_sdk)
    assert ac._model == "claude-sonnet-4-5"


def test_ollama_client_instantiates():
    """OllamaClient construction should require no network."""
    client = OllamaClient(model="llama3:8b", host="http://localhost:11434")
    assert client._model == "llama3:8b"
    assert client._host  == "http://localhost:11434"


def test_anthropic_chat_mock_end_turn():
    """AnthropicClient.chat() with end_turn response returns LLMResponse with content."""
    mock_sdk = MagicMock()
    mock_sdk.messages.create.return_value = _anthropic_end_turn_response()
    ac = _make_anthropic_client(mock_sdk)

    result = ac.chat([{"role": "user", "content": "test"}], [_make_tool()])
    assert isinstance(result, LLMResponse)
    assert result.stop_reason == "end_turn"
    assert result.content == "The root cause is a firmware failure."
    assert result.tool_calls == []


def test_anthropic_chat_mock_tool_use():
    """AnthropicClient.chat() with tool_use response returns ToolCallRequest list."""
    mock_sdk = MagicMock()
    mock_sdk.messages.create.return_value = _anthropic_tool_use_response()
    ac = _make_anthropic_client(mock_sdk)

    result = ac.chat([{"role": "user", "content": "test"}], [_make_tool()])
    assert isinstance(result, LLMResponse)
    assert result.stop_reason == "tool_use"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "get_root_cause"
    assert result.tool_calls[0].id == "toolu_01"
    assert result.content is None


def test_anthropic_system_extracted_from_messages():
    """AnthropicClient.chat() separates system message as top-level API param."""
    mock_sdk = MagicMock()
    mock_sdk.messages.create.return_value = _anthropic_end_turn_response()
    ac = _make_anthropic_client(mock_sdk)

    messages = [
        {"role": "system", "content": "You are an expert."},
        {"role": "user",   "content": "Analyse this."},
    ]
    ac.chat(messages, [_make_tool()])

    call_kwargs = mock_sdk.messages.create.call_args[1]
    assert call_kwargs.get("system") == "You are an expert."
    # system message must NOT appear in the messages list
    for msg in call_kwargs["messages"]:
        assert msg.get("role") != "system"


def test_anthropic_tool_schema_uses_input_schema_key():
    """Tool.to_anthropic_schema() uses 'input_schema' not 'parameters'."""
    tool   = _make_tool(params={"event_id": {"type": "integer"}})
    schema = tool.to_anthropic_schema()
    assert "input_schema" in schema
    assert "parameters"   not in schema
    assert schema["name"] == "get_root_cause"
    assert schema["input_schema"]["properties"] == {"event_id": {"type": "integer"}}


def test_anthropic_client_reads_api_key_from_env(monkeypatch):
    """AnthropicClient reads ANTHROPIC_API_KEY from environment via SDK."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    mock_anthropic_module = MagicMock()
    mock_sdk              = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_sdk

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        AnthropicClient(model="claude-sonnet-4-5")

    mock_anthropic_module.Anthropic.assert_called_once()


def test_ollama_chat_mock_end_turn():
    """OllamaClient.chat() with end_turn response returns LLMResponse with content."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {"content": "Analysis complete.", "tool_calls": []}
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_response):
        oc = OllamaClient()
        result = oc.chat([{"role": "user", "content": "test"}], [_make_tool()])

    assert isinstance(result, LLMResponse)
    assert result.stop_reason == "end_turn"
    assert result.content == "Analysis complete."
    assert result.tool_calls == []


def test_ollama_chat_mock_tool_calls():
    """OllamaClient.chat() with tool_calls returns ToolCallRequest list."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {
            "content": None,
            "tool_calls": [
                {
                    "id": "ollama_0",
                    "function": {"name": "get_root_cause", "arguments": {}},
                }
            ],
        }
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_response):
        oc = OllamaClient()
        result = oc.chat([{"role": "user", "content": "test"}], [_make_tool()])

    assert result.stop_reason == "tool_use"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "get_root_cause"
    assert result.tool_calls[0].id == "ollama_0"


def test_llm_response_fields():
    """LLMResponse dataclass fields are accessible."""
    resp = LLMResponse(
        content="test", tool_calls=[], stop_reason="end_turn", usage={}
    )
    assert resp.content == "test"
    assert resp.stop_reason == "end_turn"
    assert resp.tool_calls == []
    assert resp.usage == {}


def test_tool_call_request_fields():
    """ToolCallRequest dataclass fields are accessible."""
    tcr = ToolCallRequest(id="toolu_01", tool_name="get_root_cause", arguments={"x": 1})
    assert tcr.id == "toolu_01"
    assert tcr.tool_name == "get_root_cause"
    assert tcr.arguments == {"x": 1}


def test_ollama_client_custom_host():
    """OllamaClient uses custom host."""
    oc = OllamaClient(host="http://192.168.1.10:11434")
    assert oc._host == "http://192.168.1.10:11434"


def test_chat_temperature_default_0_1():
    """AnthropicClient.chat() passes temperature=0.1 by default."""
    mock_sdk = MagicMock()
    mock_sdk.messages.create.return_value = _anthropic_end_turn_response()
    ac = _make_anthropic_client(mock_sdk)
    ac.chat([], [_make_tool()])
    call_kwargs = mock_sdk.messages.create.call_args[1]
    assert call_kwargs["temperature"] == 0.1


def test_chat_max_tokens_default_2048():
    """AnthropicClient.chat() passes max_tokens=2048 by default."""
    mock_sdk = MagicMock()
    mock_sdk.messages.create.return_value = _anthropic_end_turn_response()
    ac = _make_anthropic_client(mock_sdk)
    ac.chat([], [_make_tool()])
    call_kwargs = mock_sdk.messages.create.call_args[1]
    assert call_kwargs["max_tokens"] == 2048


def test_anthropic_connect_error_raises():
    """AnthropicClient.chat() propagates exceptions from the anthropic SDK."""
    mock_sdk = MagicMock()
    mock_sdk.messages.create.side_effect = Exception("Connection refused")
    ac = _make_anthropic_client(mock_sdk)

    with pytest.raises(Exception, match="Connection refused"):
        ac.chat([], [_make_tool()])


def test_ollama_connect_error_raises():
    """OllamaClient.chat() propagates httpx.ConnectError."""
    connect_error = Exception("Connection refused")
    with patch("httpx.post", side_effect=connect_error):
        oc = OllamaClient()
        with pytest.raises(Exception):
            oc.chat([], [_make_tool()])
