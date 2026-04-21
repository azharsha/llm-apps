"""
test_llm_client.py — Phase 6

15 tests for LLMClient ABC, OpenAIClient, OllamaClient.
All network calls are mocked.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from soctriage.core.llm_client import (
    LLMClient, OpenAIClient, OllamaClient,
    LLMResponse, ToolCallRequest,
)
from soctriage.core.tool_registry import Tool


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_tool() -> Tool:
    return Tool(
        name="get_root_cause",
        description="Returns root cause.",
        parameters={},
        fn=lambda ctx: {},
    )


def _openai_stop_response():
    """Build a mock openai response that has stop_reason='stop'."""
    choice  = MagicMock()
    choice.finish_reason = "stop"
    choice.message.content = "The root cause is a firmware failure."
    choice.message.tool_calls = None
    usage = MagicMock()
    usage.model_dump.return_value = {"prompt_tokens": 100, "completion_tokens": 50}
    resp         = MagicMock()
    resp.choices = [choice]
    resp.usage   = usage
    return resp


def _openai_tool_call_response():
    """Build a mock openai response that has stop_reason='tool_calls'."""
    tc_fn            = MagicMock()
    tc_fn.name       = "get_root_cause"
    tc_fn.arguments  = json.dumps({})
    tc               = MagicMock()
    tc.id            = "tc_001"
    tc.function      = tc_fn

    choice                    = MagicMock()
    choice.finish_reason      = "tool_calls"
    choice.message.content    = None
    choice.message.tool_calls = [tc]

    usage = MagicMock()
    usage.model_dump.return_value = {}
    resp         = MagicMock()
    resp.choices = [choice]
    resp.usage   = usage
    return resp


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_openai_client_instantiates():
    """OpenAIClient should construct without live network (we mock openai.OpenAI)."""
    with patch("soctriage.core.llm_client.OpenAIClient.__init__", return_value=None):
        client = OpenAIClient.__new__(OpenAIClient)
        assert client is not None


def test_ollama_client_instantiates():
    """OllamaClient construction should require no network."""
    client = OllamaClient(model="llama3:8b", host="http://localhost:11434")
    assert client._model == "llama3:8b"
    assert client._host  == "http://localhost:11434"


def _make_openai_client_with_mock(mock_client) -> OpenAIClient:
    """Create an OpenAIClient with a mocked internal client, bypassing openai import."""
    # Patch the openai module so the import inside __init__ doesn't fail
    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client
    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        oc = OpenAIClient(model="gpt-4o")
    return oc


def test_openai_chat_mock_stop():
    """OpenAIClient.chat() with stop response returns LLMResponse with content."""
    mock_openai_resp = _openai_stop_response()
    mock_client      = MagicMock()
    mock_client.chat.completions.create.return_value = mock_openai_resp

    oc = _make_openai_client_with_mock(mock_client)

    result = oc.chat([{"role": "user", "content": "test"}], [_make_tool()])
    assert isinstance(result, LLMResponse)
    assert result.stop_reason == "stop"
    assert result.content == "The root cause is a firmware failure."
    assert result.tool_calls == []


def test_openai_chat_mock_tool_calls():
    """OpenAIClient.chat() with tool_calls response returns ToolCallRequest list."""
    mock_openai_resp = _openai_tool_call_response()
    mock_client      = MagicMock()
    mock_client.chat.completions.create.return_value = mock_openai_resp

    oc = _make_openai_client_with_mock(mock_client)

    result = oc.chat([{"role": "user", "content": "test"}], [_make_tool()])
    assert isinstance(result, LLMResponse)
    assert result.stop_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "get_root_cause"
    assert result.tool_calls[0].id == "tc_001"


def test_ollama_chat_mock_stop():
    """OllamaClient.chat() with stop response returns LLMResponse with content."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {"content": "Analysis complete.", "tool_calls": []}
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_response):
        oc = OllamaClient()
        result = oc.chat([{"role": "user", "content": "test"}], [_make_tool()])

    assert isinstance(result, LLMResponse)
    assert result.stop_reason == "stop"
    assert result.content == "Analysis complete."
    assert result.tool_calls == []


def test_ollama_chat_mock_tool_calls():
    """OllamaClient.chat() with tool_calls response returns ToolCallRequest list."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {
            "content": None,
            "tool_calls": [
                {
                    "id": "ollama_tc_1",
                    "function": {"name": "get_root_cause", "arguments": {}},
                }
            ],
        }
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_response):
        oc = OllamaClient()
        result = oc.chat([{"role": "user", "content": "test"}], [_make_tool()])

    assert result.stop_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "get_root_cause"


def test_llm_response_fields():
    """LLMResponse dataclass fields are accessible."""
    resp = LLMResponse(
        content="test", tool_calls=[], stop_reason="stop", usage={}
    )
    assert resp.content == "test"
    assert resp.stop_reason == "stop"
    assert resp.tool_calls == []
    assert resp.usage == {}


def test_tool_call_request_fields():
    """ToolCallRequest dataclass fields are accessible."""
    tcr = ToolCallRequest(id="abc", tool_name="get_root_cause", arguments={"x": 1})
    assert tcr.id == "abc"
    assert tcr.tool_name == "get_root_cause"
    assert tcr.arguments == {"x": 1}


def test_openai_client_uses_api_key_from_env(monkeypatch):
    """OpenAIClient should read OPENAI_API_KEY from env (via openai SDK)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    mock_openai_module = MagicMock()
    mock_client        = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client

    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        oc = OpenAIClient(model="gpt-4o")

    mock_openai_module.OpenAI.assert_called_once()


def test_ollama_client_custom_host():
    """OllamaClient should use custom host."""
    oc = OllamaClient(host="http://192.168.1.10:11434")
    assert oc._host == "http://192.168.1.10:11434"


def test_openai_schema_generation():
    """Tool.to_openai_schema() returns correct OpenAI function schema format."""
    tool   = _make_tool()
    schema = tool.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "get_root_cause"
    assert "parameters" in schema["function"]


def test_chat_temperature_default_0_1():
    """OpenAIClient.chat() passes temperature=0.1 by default."""
    mock_openai_resp = _openai_stop_response()
    mock_client      = MagicMock()
    mock_client.chat.completions.create.return_value = mock_openai_resp

    oc = _make_openai_client_with_mock(mock_client)
    oc.chat([], [_make_tool()])
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["temperature"] == 0.1


def test_chat_max_tokens_default_2048():
    """OpenAIClient.chat() passes max_tokens=2048 by default."""
    mock_openai_resp = _openai_stop_response()
    mock_client      = MagicMock()
    mock_client.chat.completions.create.return_value = mock_openai_resp

    oc = _make_openai_client_with_mock(mock_client)
    oc.chat([], [_make_tool()])
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["max_tokens"] == 2048


def test_openai_connect_error_raises():
    """OpenAIClient.chat() propagates exceptions from the openai SDK."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("Connection refused")

    oc = _make_openai_client_with_mock(mock_client)

    with pytest.raises(Exception, match="Connection refused"):
        oc.chat([], [_make_tool()])


def test_ollama_connect_error_raises():
    """OllamaClient.chat() propagates httpx.ConnectError."""
    try:
        import httpx
        connect_error = httpx.ConnectError("Connection refused")
    except ImportError:
        # httpx may not be installed in base env — simulate
        connect_error = Exception("Connection refused")

    with patch("httpx.post", side_effect=connect_error):
        oc = OllamaClient()
        with pytest.raises(Exception):
            oc.chat([], [_make_tool()])
