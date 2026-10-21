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
from typing import Any

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
