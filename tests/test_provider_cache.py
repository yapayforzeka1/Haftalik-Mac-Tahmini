
"""Offline tests for the football-data fixture cache."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

import providers
from learning import digest
from providers import CachedFootball


NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
NOW_TS = NOW.timestamp()
PATH = "/competitions/CL/matches"
PARAMS = {"season": 2026}


def fixture(hours, status="TIMED"):
    kickoff = NOW + timedelta(hours=hours)
    return {
        "status": status,
        "utcDate": kickoff.isoformat().replace("+00:00", "Z"),
    }


def make_client(monkeypatch, matches, age):
    """Create a cache client without network access."""
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "offline-test-key")

    key = digest([PATH, PARAMS])
    data = {"matches": matches}
    cache = {
        key: {
            "at": NOW_TS - age,
            "data": data,
        }
    }

    saved = Mock()
    client = CachedFootball(cache, saved)
    return client, cache, saved


def block_network(monkeypatch):
    """Fail immediately if the test makes a real HTTP request."""
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network request")

    monkeypatch.setattr(providers.requests, "get", forbidden)


def mock_network(monkeypatch, matches):
    """Return a fake HTTP response and count requests."""
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"matches": matches}

    get = Mock(return_value=response)
    monkeypatch.setattr(providers.requests, "get", get)
    return get


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(providers.time, "time", lambda: NOW_TS)
    monkeypatch.setattr(providers.time, "sleep", lambda _: None)


def test_valid_long_cache_avoids_api(monkeypatch):
    client, cache, saved = make_client(
        monkeypatch, [fixture(48)], age=1800
    )
    block_network(monkeypatch)

    result = client._get(PATH, PARAMS)

    assert result == {"matches": [fixture(48)]}
    saved.assert_not_called()


def test_expired_long_cache_refreshes(monkeypatch):
    client, cache, saved = make_client(
        monkeypatch, [fixture(48)], age=3700
    )
    get = mock_network(monkeypatch, [fixture(48)])

    client._get(PATH, PARAMS)

    get.assert_called_once()
    saved.assert_called_once()


def test_valid_medium_cache_avoids_api(monkeypatch):
    client, cache, saved = make_client(
        monkeypatch, [fixture(12)], age=600
    )
    block_network(monkeypatch)

    client._get(PATH, PARAMS)

    saved.assert_not_called()


def test_expired_medium_cache_refreshes(monkeypatch):
    client, cache, saved = make_client(
        monkeypatch, [fixture(12)], age=1000
    )
    get = mock_network(monkeypatch, [fixture(12)])

    client._get(PATH, PARAMS)

    get.assert_called_once()


def test_near_kickoff_uses_short_ttl(monkeypatch):
    client, cache, saved = make_client(
        monkeypatch, [fixture(1)], age=300
    )
    get = mock_network(monkeypatch, [fixture(1)])

    client._get(PATH, PARAMS)

    get.assert_called_once()


def test_valid_short_cache_avoids_api(monkeypatch):
    client, cache, saved = make_client(
        monkeypatch, [fixture(1)], age=120
    )
    block_network(monkeypatch)

    client._get(PATH, PARAMS)

    saved.assert_not_called()


@pytest.mark.parametrize("status", ["POSTPONED", "CANCELLED"])
def test_old_inactive_fixture_does_not_force_short_ttl(
    monkeypatch, status
):
    """An old inactive fixture should not force 4-minute refreshes."""
    matches = [
        fixture(-720, status),
        fixture(72, "TIMED"),
    ]
    client, cache, saved = make_client(
        monkeypatch, matches, age=600
    )
    block_network(monkeypatch)

    client._get(PATH, PARAMS)

    saved.assert_not_called()


def test_invalid_cache_entry_fetches_fresh_data(monkeypatch):
    client, cache, saved = make_client(
        monkeypatch, [fixture(48)], age=100
    )
    key = digest([PATH, PARAMS])
    cache[key] = {"at": "invalid", "data": {}}

    get = mock_network(monkeypatch, [fixture(48)])

    client._get(PATH, PARAMS)

    get.assert_called_once()
    saved.assert_called_once()


def test_fresh_response_survives_cleanup_and_is_reused(monkeypatch):
    """A newly cached response must not be deleted by a stale clock value."""
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "offline-test-key")
    key = digest([PATH, PARAMS])
    cache = {}
    saved = Mock()
    client = CachedFootball(cache, saved)
    get = mock_network(monkeypatch, [fixture(48)])

    # The original bug used the first time (1000) to compare against the
    # newly written entry (1001), yielding a negative age and deleting it.
    clock = iter([NOW_TS, NOW_TS + 1, NOW_TS + 1])
    monkeypatch.setattr(providers.time, "time", lambda: next(clock))

    first = client._get(PATH, PARAMS)

    assert cache[key]["data"] == first
    assert cache[key]["at"] == NOW_TS + 1
    get.assert_called_once()
    saved.assert_called_once()

    # A subsequent invocation must reuse the just-saved snapshot.
    block_network(monkeypatch)
    monkeypatch.setattr(providers.time, "time", lambda: NOW_TS + 30)
    assert client._get(PATH, PARAMS) == first
    saved.assert_called_once()


def test_cleanup_removes_expired_entries_but_keeps_new_entry(monkeypatch):
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "offline-test-key")
    key = digest([PATH, PARAMS])
    cache = {
        "expired": {"at": NOW_TS - 90000, "data": {}},
        "invalid": {"at": "invalid", "data": {}},
    }
    saved = Mock()
    client = CachedFootball(cache, saved)
    mock_network(monkeypatch, [fixture(48)])
    clock = iter([NOW_TS, NOW_TS + 1, NOW_TS + 1])
    monkeypatch.setattr(providers.time, "time", lambda: next(clock))

    client._get(PATH, PARAMS)

    assert set(cache) == {key}
    saved.assert_called_once()
