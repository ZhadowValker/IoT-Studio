import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent import llm  # noqa: E402


def test_openai_stream_text_and_split_tool_call():
    a = llm._OpenAIStream()
    chunks = [
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "write_file", "arguments": '{"na'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'me":"a"}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}},
    ]
    shown = "".join(a.feed(c) for c in chunks)
    r = a.reply()
    assert shown == "Hello" and r["content"] == "Hello"
    assert r["tool_calls"] == [{"id": "c1", "name": "write_file", "arguments": '{"name":"a"}'}]
    assert r["finish_reason"] == "tool_calls" and r["usage"] == {"input": 5, "output": 7}


def test_anthropic_stream():
    a = llm._AnthropicStream()
    evs = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 11}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "run"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{}"}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 3}},
    ]
    assert "".join(a.feed(e) for e in evs) == "Hi"
    r = a.reply()
    assert r["tool_calls"] == [{"id": "t1", "name": "run", "arguments": "{}"}]
    assert r["usage"] == {"input": 11, "output": 3} and r["finish_reason"] == "tool_use"


def test_stream_complete_end_to_end(monkeypatch):
    import asyncio
    import httpx

    sse = "".join(
        f"data: {json.dumps(c)}\n\n" for c in [
            {"choices": [{"delta": {"content": "ok"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
    ) + "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    real = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("IOT_AGENT_ALLOW_PRIVATE_URLS", "1")

    async def run():
        return [e async for e in llm.stream_complete(
            {"format": "openai", "base_url": "http://127.0.0.1:1/v1", "model": "m", "messages": []}, "SECRET")]

    evs = asyncio.run(run())
    assert [e["t"] for e in evs] == ["text", "done"] and evs[-1]["reply"]["content"] == "ok"


def test_stream_error_is_scrubbed(monkeypatch):
    import asyncio
    import httpx

    def handler(request):
        return httpx.Response(401, text="bad key SECRET")

    real = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("IOT_AGENT_ALLOW_PRIVATE_URLS", "1")

    async def run():
        return [e async for e in llm.stream_complete(
            {"format": "openai", "base_url": "http://127.0.0.1:1/v1", "model": "m", "messages": []}, "SECRET")]

    evs = asyncio.run(run())
    assert evs[-1]["t"] == "error" and "SECRET" not in evs[-1]["message"] and evs[-1]["status"] == 401
