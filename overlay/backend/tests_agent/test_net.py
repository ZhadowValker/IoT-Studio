import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent.net import UnsafeUrl, validate_base_url  # noqa: E402


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434", "http://localhost:11434", "http://10.0.0.5/v1",
    "http://192.168.1.2", "http://169.254.169.254/latest", "http://[::1]/",
    "file:///etc/passwd", "ftp://example.com", "https://user:pw@8.8.8.8/",
])
def test_blocked(url, monkeypatch):
    monkeypatch.delenv("IOT_AGENT_ALLOW_PRIVATE_URLS", raising=False)
    with pytest.raises(UnsafeUrl):
        validate_base_url(url, resolve=False)


def test_public_ok(monkeypatch):
    monkeypatch.delenv("IOT_AGENT_ALLOW_PRIVATE_URLS", raising=False)
    assert validate_base_url("https://api.openai.com/v1/", resolve=False) == "https://api.openai.com/v1"
    assert validate_base_url("https://8.8.8.8", resolve=False) == "https://8.8.8.8"


def test_private_opt_in(monkeypatch):
    monkeypatch.setenv("IOT_AGENT_ALLOW_PRIVATE_URLS", "1")
    assert validate_base_url("http://localhost:11434", resolve=False) == "http://localhost:11434"
