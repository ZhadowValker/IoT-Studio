import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent import llm  # noqa: E402

TOOLS = [{"name": "read_file", "description": "d",
          "parameters": {"type": "object", "properties": {"name": {"type": "string"}}}}]

CONVO = [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "a", "type": "function", "function": {"name": "read_file", "arguments": '{"name":"x"}'}},
        {"id": "b", "type": "function", "function": {"name": "read_file", "arguments": '{"name":"y"}'}}]},
    {"role": "tool", "tool_call_id": "a", "content": "AAA"},
    {"role": "tool", "tool_call_id": "b", "content": "BBB"},
]


def test_openai_payload():
    p = llm.to_openai_payload({"model": "m", "system": "S", "messages": CONVO, "tools": TOOLS})
    assert p["messages"][0] == {"role": "system", "content": "S"}
    assert p["tools"][0]["function"]["name"] == "read_file" and p["tool_choice"] == "auto"


def test_anthropic_payload_groups_tool_results():
    p = llm.to_anthropic_payload({"model": "m", "system": "S", "messages": CONVO, "tools": TOOLS})
    assert p["system"] == "S" and "input_schema" in p["tools"][0]
    assert [m["role"] for m in p["messages"]] == ["user", "assistant", "user"]
    assert len(p["messages"][2]["content"]) == 2
    assert p["messages"][1]["content"][0] == {"type": "tool_use", "id": "a", "name": "read_file", "input": {"name": "x"}}


def test_parse_responses():
    o = llm.from_openai_response({"choices": [{"message": {"content": "", "tool_calls": [
        {"id": "1", "function": {"name": "n", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4}})
    assert o["tool_calls"][0]["name"] == "n" and o["usage"] == {"input": 3, "output": 4}
    a = llm.from_anthropic_response({"content": [{"type": "text", "text": "hi"},
        {"type": "tool_use", "id": "t", "name": "n", "input": {"a": 1}}], "stop_reason": "tool_use"})
    assert a["content"] == "hi" and json.loads(a["tool_calls"][0]["arguments"]) == {"a": 1}


def _run(req, key, handler):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await llm.complete(req, key, client=c)
    return asyncio.run(go())


def test_complete_sends_key_and_hides_it_in_errors():
    seen = {}

    def ok(request):
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    r = _run({"format": "openai", "base_url": "https://8.8.8.8/v1", "model": "m", "messages": []}, "SECRET", ok)
    assert r["content"] == "OK" and seen["auth"] == "Bearer SECRET"
    assert seen["url"] == "https://8.8.8.8/v1/chat/completions"

    def bad(request):
        return httpx.Response(401, text="invalid key SECRET")

    with pytest.raises(llm.LlmError) as e:
        _run({"format": "openai", "base_url": "https://8.8.8.8/v1", "model": "m", "messages": []}, "SECRET", bad)
    assert "SECRET" not in e.value.message and "rejected" in e.value.message


def test_private_url_refused(monkeypatch):
    monkeypatch.delenv("IOT_AGENT_ALLOW_PRIVATE_URLS", raising=False)
    with pytest.raises(llm.LlmError):
        _run({"format": "openai", "base_url": "http://127.0.0.1:1", "model": "m", "messages": []}, "k",
             lambda r: httpx.Response(200, json={}))


def test_list_models_sorted_and_key_scrubbed():
    def ok(request):
        assert request.headers.get("authorization") == "Bearer SECRET"
        return httpx.Response(200, json={"data": [{"id": "b/model"}, {"id": "a/model"}, {"id": "a/model"}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(ok)) as c:
            return await llm.list_models({"format": "openai", "base_url": "https://8.8.8.8/v1"}, "SECRET", client=c)
    assert asyncio.run(go()) == ["a/model", "b/model"]
