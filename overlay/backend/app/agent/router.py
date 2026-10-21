"""IoT-Studio agent API (overlay). M0: status + URL check.

The LLM proxy (/llm) and the external-agent bridge arrive in later milestones.
The user's API key is only ever read from a request header and is never
stored or logged.
"""
from __future__ import annotations

import os

from typing import Any

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.agent import llm

from app.agent.net import UnsafeUrl, validate_base_url

router = APIRouter()


@router.get("/status")
async def status() -> dict:
    return {
        "enabled": os.environ.get("IOT_AGENT", "on") != "off",
        "milestone": "M2",
        "allow_private_urls": os.environ.get("IOT_AGENT_ALLOW_PRIVATE_URLS", "") == "1",
    }


class UrlCheck(BaseModel):
    base_url: str


@router.post("/check-url")
async def check_url(body: UrlCheck) -> dict:
    """Lets the panel tell the user right away if a provider URL is refused."""
    try:
        return {"ok": True, "base_url": validate_base_url(body.base_url)}
    except UnsafeUrl as exc:
        return {"ok": False, "error": str(exc)}


class LlmRequest(BaseModel):
    format: str = "openai"
    base_url: str
    model: str
    system: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    max_tokens: int = Field(default=4096, ge=1, le=16000)


@router.post("/llm")
async def llm_turn(body: LlmRequest, x_agent_key: str = Header(default="")) -> JSONResponse:
    """One model turn. The user's key comes only from the X-Agent-Key header."""
    try:
        result = await llm.complete(body.model_dump(), x_agent_key)
    except llm.LlmError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status)
    return JSONResponse(result)


class ModelsRequest(BaseModel):
    format: str = "openai"
    base_url: str


@router.post("/models")
async def list_models(body: ModelsRequest, x_agent_key: str = Header(default="")) -> JSONResponse:
    """Lists the provider's model ids so the panel can offer real choices."""
    try:
        ids = await llm.list_models(body.model_dump(), x_agent_key)
    except llm.LlmError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status)
    return JSONResponse({"models": ids})
