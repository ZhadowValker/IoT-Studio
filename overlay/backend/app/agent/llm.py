"""LLM proxy for the IoT-Studio agent.

The browser speaks ONE neutral format (OpenAI-style messages + tool calls) and
this module adapts it to the provider's wire format:

  * ``openai``    - chat completions (OpenAI, NVIDIA, Gemini, OpenRouter,
                    Groq, Ollama, any compatible server)
  * ``anthropic`` - Anthropic Messages API

The user's API key arrives per request and is only forwarded to the provider.
It is never stored or logged, and is scrubbed from any error text.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from app.agent.net import UnsafeUrl, validate_base_url

TIMEOUT = httpx.Timeout(120.0, connect=15.0)
ANTHROPIC_VERSION = "2023-06-01"


class LlmError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


def scrub(text: str, key: str) -> str:
    if key and key in text:
        text = text.replace(key, "***")
    return text[:1500]


# ── neutral -> provider ──────────────────────────────────────────────────────


def to_openai_payload(req: dict) -> dict:
    messages: list[dict] = []
    if req.get("system"):
        messages.append({"role": "system", "content": req["system"]})
    messages.extend(req.get("messages", []))
    payload: dict[str, Any] = {
        "model": req["model"],
        "messages": messages,
        "max_tokens": req.get("max_tokens", 4096),
    }
    tools = req.get("tools") or []
    if tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]
        payload["tool_choice"] = "auto"
    return payload


def to_anthropic_payload(req: dict) -> dict:
    out: list[dict] = []
    for m in req.get("messages", []):
        role = m.get("role")
        if role == "assistant":
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                blocks.append(
                    {"type": "tool_use", "id": tc["id"], "name": fn.get("name"), "input": args}
                )
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m["tool_call_id"],
                "content": m.get("content", ""),
            }
            # Consecutive tool results must share ONE user message.
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) and all(
                b.get("type") == "tool_result" for b in out[-1]["content"]
            ):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        else:
            out.append({"role": "user", "content": m.get("content", "")})
    payload: dict[str, Any] = {
        "model": req["model"],
        "max_tokens": req.get("max_tokens", 4096),
        "messages": out,
    }
    if req.get("system"):
        payload["system"] = req["system"]
    tools = req.get("tools") or []
    if tools:
        payload["tools"] = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]
    return payload


# ── provider -> neutral ──────────────────────────────────────────────────────


def from_openai_response(data: dict) -> dict:
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        calls.append(
            {"id": tc.get("id") or f"call_{len(calls)}", "name": fn.get("name"),
             "arguments": fn.get("arguments") or "{}"}
        )
    usage = data.get("usage") or {}
    return {
        "content": msg.get("content") or "",
        "tool_calls": calls,
        "finish_reason": choice.get("finish_reason"),
        "usage": {
            "input": usage.get("prompt_tokens", 0),
            "output": usage.get("completion_tokens", 0),
        },
    }


def from_anthropic_response(data: dict) -> dict:
    text: list[str] = []
    calls = []
    for block in data.get("content") or []:
        if block.get("type") == "text":
            text.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            calls.append(
                {"id": block["id"], "name": block["name"],
                 "arguments": json.dumps(block.get("input") or {})}
            )
    usage = data.get("usage") or {}
    return {
        "content": "".join(text),
        "tool_calls": calls,
        "finish_reason": data.get("stop_reason"),
        "usage": {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)},
    }


# ── call ─────────────────────────────────────────────────────────────────────


async def complete(req: dict, api_key: str, client: httpx.AsyncClient | None = None) -> dict:
    """Run one model turn. Raises LlmError with a key-free message."""
    fmt = req.get("format", "openai")
    if fmt not in ("openai", "anthropic"):
        raise LlmError("Unknown provider format", 400)
    if not req.get("model"):
        raise LlmError("Choose a model first", 400)
    try:
        base = validate_base_url(req.get("base_url", ""))
    except UnsafeUrl as exc:
        raise LlmError(str(exc), 400) from exc

    if fmt == "anthropic":
        url = f"{base}/v1/messages"
        headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION,
                   "content-type": "application/json"}
        payload = to_anthropic_payload(req)
        parse = from_anthropic_response
    else:
        url = f"{base}/chat/completions"
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        payload = to_openai_payload(req)
        parse = from_openai_response

    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
    try:
        resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise LlmError("The model provider timed out", 504) from exc
    except httpx.HTTPError as exc:
        raise LlmError(scrub(f"Could not reach the provider: {exc}", api_key), 502) from exc
    finally:
        if own:
            await client.aclose()

    if resp.status_code >= 400:
        detail = scrub(resp.text, api_key)
        hint = {401: "The API key was rejected.", 403: "The API key is not allowed to do this.",
                404: "Model or endpoint not found - check the model id and base URL.",
                429: "Rate limit or quota reached."}.get(resp.status_code, "")
        raise LlmError(f"Provider error {resp.status_code}. {hint} {detail}".strip(),
                       resp.status_code if resp.status_code in (400, 401, 403, 404, 429) else 502)
    try:
        return parse(resp.json())
    except Exception as exc:  # malformed provider reply
        raise LlmError("The provider returned an unexpected response", 502) from exc


# ── streaming ────────────────────────────────────────────────────────────────


class _OpenAIStream:
    """Folds chat-completions SSE chunks into one neutral reply."""

    def __init__(self) -> None:
        self.text: list[str] = []
        self.calls: dict[int, dict] = {}
        self.finish: str | None = None
        self.usage = {"input": 0, "output": 0}

    def feed(self, data: dict) -> str:
        u = data.get("usage")
        if u:
            self.usage = {"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)}
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason"):
            self.finish = choice["finish_reason"]
        delta = choice.get("delta") or {}
        for tc in delta.get("tool_calls") or []:
            slot = self.calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] += fn["name"]
            if fn.get("arguments"):
                slot["arguments"] += fn["arguments"]
        piece = delta.get("content") or ""
        if piece:
            self.text.append(piece)
        return piece

    def reply(self) -> dict:
        calls = []
        for i in sorted(self.calls):
            c = self.calls[i]
            calls.append({"id": c["id"] or f"call_{i}", "name": c["name"], "arguments": c["arguments"] or "{}"})
        return {"content": "".join(self.text), "tool_calls": calls,
                "finish_reason": self.finish, "usage": self.usage}


class _AnthropicStream:
    """Folds Messages API SSE events into one neutral reply."""

    def __init__(self) -> None:
        self.text: list[str] = []
        self.blocks: dict[int, dict] = {}
        self.finish: str | None = None
        self.usage = {"input": 0, "output": 0}

    def feed(self, data: dict) -> str:
        t = data.get("type")
        if t == "message_start":
            u = (data.get("message") or {}).get("usage") or {}
            self.usage["input"] = u.get("input_tokens", 0)
        elif t == "content_block_start":
            blk = data.get("content_block") or {}
            if blk.get("type") == "tool_use":
                self.blocks[data.get("index", 0)] = {"id": blk.get("id", ""), "name": blk.get("name", ""), "arguments": ""}
        elif t == "content_block_delta":
            d = data.get("delta") or {}
            if d.get("type") == "text_delta":
                self.text.append(d.get("text", ""))
                return d.get("text", "")
            if d.get("type") == "input_json_delta":
                b = self.blocks.get(data.get("index", 0))
                if b is not None:
                    b["arguments"] += d.get("partial_json", "")
        elif t == "message_delta":
            self.finish = (data.get("delta") or {}).get("stop_reason") or self.finish
            self.usage["output"] = (data.get("usage") or {}).get("output_tokens", self.usage["output"])
        return ""

    def reply(self) -> dict:
        calls = [{"id": b["id"], "name": b["name"], "arguments": b["arguments"] or "{}"}
                 for _, b in sorted(self.blocks.items())]
        return {"content": "".join(self.text), "tool_calls": calls,
                "finish_reason": self.finish, "usage": self.usage}


async def stream_complete(req: dict, api_key: str) -> AsyncIterator[dict]:
    """One model turn as events: {"t":"text","d":..} ... then {"t":"done","reply":{..}}
    or {"t":"error","message":..,"status":..}. Never raises; errors are key-free."""
    fmt = req.get("format", "openai")
    try:
        if fmt not in ("openai", "anthropic"):
            raise LlmError("Unknown provider format", 400)
        if not req.get("model"):
            raise LlmError("Choose a model first", 400)
        try:
            base = validate_base_url(req.get("base_url", ""))
        except UnsafeUrl as exc:
            raise LlmError(str(exc), 400) from exc
        if fmt == "anthropic":
            url = f"{base}/v1/messages"
            headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION,
                       "content-type": "application/json"}
            payload = {**to_anthropic_payload(req), "stream": True}
            acc: Any = _AnthropicStream()
        else:
            url = f"{base}/chat/completions"
            headers = {"content-type": "application/json"}
            if api_key:
                headers["authorization"] = f"Bearer {api_key}"
            payload = {**to_openai_payload(req), "stream": True}
            acc = _OpenAIStream()

        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            try:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 400:
                        detail = scrub((await resp.aread()).decode("utf-8", "replace"), api_key)
                        hint = {401: "The API key was rejected.", 403: "The API key is not allowed to do this.",
                                404: "Model or endpoint not found - check the model id and base URL.",
                                429: "Rate limit or quota reached."}.get(resp.status_code, "")
                        raise LlmError(f"Provider error {resp.status_code}. {hint} {detail}".strip(),
                                       resp.status_code if resp.status_code in (400, 401, 403, 404, 429) else 502)
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        body = line[5:].strip()
                        if not body or body == "[DONE]":
                            continue
                        try:
                            piece = acc.feed(json.loads(body))
                        except json.JSONDecodeError:
                            continue
                        if piece:
                            yield {"t": "text", "d": piece}
            except httpx.TimeoutException as exc:
                raise LlmError("The model provider timed out", 504) from exc
            except httpx.HTTPError as exc:
                raise LlmError(scrub(f"Could not reach the provider: {exc}", api_key), 502) from exc
        yield {"t": "done", "reply": acc.reply()}
    except LlmError as exc:
        yield {"t": "error", "message": exc.message, "status": exc.status}
    except Exception:  # never leak internals or the key
        yield {"t": "error", "message": "The model stream failed unexpectedly", "status": 502}


async def list_models(req: dict, api_key: str, client: httpx.AsyncClient | None = None) -> list[str]:
    """Model ids the provider offers (GET /models). Key-free errors."""
    fmt = req.get("format", "openai")
    try:
        base = validate_base_url(req.get("base_url", ""))
    except UnsafeUrl as exc:
        raise LlmError(str(exc), 400) from exc
    if fmt == "anthropic":
        url = f"{base}/v1/models?limit=100"
        headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
    else:
        url = f"{base}/models"
        headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
    try:
        resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise LlmError(scrub(f"Could not reach the provider: {exc}", api_key), 502) from exc
    finally:
        if own:
            await client.aclose()
    if resp.status_code >= 400:
        raise LlmError(f"Provider error {resp.status_code}. {scrub(resp.text, api_key)}",
                       resp.status_code if resp.status_code in (400, 401, 403, 404, 429) else 502)
    try:
        items = resp.json().get("data") or []
        return sorted({str(i.get("id")) for i in items if i.get("id")})
    except Exception as exc:
        raise LlmError("The provider returned an unexpected model list", 502) from exc
