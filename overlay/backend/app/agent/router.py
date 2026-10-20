"""IoT-Studio agent API (overlay). M0: status + URL check.

The LLM proxy (/llm) and the external-agent bridge arrive in later milestones.
The user's API key is only ever read from a request header and is never
stored or logged.
"""
from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from app.agent.net import UnsafeUrl, validate_base_url

router = APIRouter()


@router.get("/status")
async def status() -> dict:
    return {
        "enabled": os.environ.get("IOT_AGENT", "on") != "off",
        "milestone": "M0",
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
