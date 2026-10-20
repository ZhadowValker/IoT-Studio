"""Outbound URL guard for the agent's LLM proxy.

The user supplies the provider base URL, so the proxy must not become a way to
reach the server's private network (SSRF). Private, loopback, link-local and
metadata addresses are refused unless the deployer opts in with
IOT_AGENT_ALLOW_PRIVATE_URLS=1 (needed for a local Ollama).
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


class UnsafeUrl(ValueError):
    pass


def _allow_private() -> bool:
    return os.environ.get("IOT_AGENT_ALLOW_PRIVATE_URLS", "") == "1"


def _is_blocked(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_base_url(url: str, *, resolve: bool = True) -> str:
    """Return the normalised URL or raise UnsafeUrl."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrl("URL must start with http:// or https://")
    if not parsed.hostname:
        raise UnsafeUrl("URL has no host")
    if parsed.username or parsed.password:
        raise UnsafeUrl("URL must not contain credentials")

    if not _allow_private():
        host = parsed.hostname
        try:
            literal = ipaddress.ip_address(host)
            addrs = [literal]
        except ValueError:
            if host.lower() in ("localhost",) or host.lower().endswith(".localhost"):
                raise UnsafeUrl("Private/loopback addresses are not allowed")
            addrs = []
            if resolve:
                try:
                    infos = socket.getaddrinfo(host, None)
                except socket.gaierror as exc:
                    raise UnsafeUrl(f"Cannot resolve host: {host}") from exc
                addrs = [ipaddress.ip_address(i[4][0]) for i in infos]
        for ip in addrs:
            if _is_blocked(ip):
                raise UnsafeUrl("Private/loopback addresses are not allowed")

    return url.strip().rstrip("/")
