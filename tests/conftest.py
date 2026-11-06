"""Tests may not contact live providers or Telegram."""
import pytest
import requests
import httpx


@pytest.fixture(autouse=True)
def historical_gemini_fixture(monkeypatch):
    # Existing regression fixtures describe the original 3.6 model. Keep their
    # identity explicit; migration tests below exercise 3.5 separately.
    import ai_pool
    monkeypatch.setattr(ai_pool, 'GEMINI_MODEL', 'gemini-3.6-flash')


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Live network forbidden in tests; inject a fake transport.')
    monkeypatch.setattr(requests.sessions.Session, 'request', denied)
    monkeypatch.setattr(httpx.Client, 'send', denied)
