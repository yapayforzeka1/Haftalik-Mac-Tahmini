"""Tests may not contact live providers or Telegram."""
import pytest
import requests
import httpx


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Live network forbidden in tests; inject a fake transport.')
    monkeypatch.setattr(requests.sessions.Session, 'request', denied)
    monkeypatch.setattr(httpx.Client, 'send', denied)
