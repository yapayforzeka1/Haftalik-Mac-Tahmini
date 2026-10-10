"""Offline regression checks for football fixture matching (no API calls)."""
from datetime import datetime, timezone

import pytest

from data_provider import (
    APIFootballClient,
    FotMobClient,
    _normalize_team_name,
    _team_names_match,
)


def _fotmob_match(home, away, utc_time, match_id=42):
    return {"id": match_id, "home": {"name": home}, "away": {"name": away},
            "status": {"utcTime": utc_time}}


def _api_fixture(home, away, utc_time, fixture_id=43):
    return {"fixture": {"id": fixture_id, "date": utc_time},
            "teams": {"home": {"name": home}, "away": {"name": away}}}


def test_team_aliases_and_no_partial_word_removal():
    assert _team_names_match("Racing Club de Lens", "Lens")
    assert _team_names_match("Sporting Clube de Portugal", "Sporting CP")
    assert _normalize_team_name("Newcastle United") == "newcastle united"
    assert not _team_names_match("Manchester United", "Manchester City")
    assert not _team_names_match("Sporting CP", "Sporting Braga")


def test_fotmob_matches_correct_fixture_without_network(monkeypatch):
    client = FotMobClient()
    calls = []
    def fake_matches(date):
        calls.append(date)
        return [_fotmob_match("Lens", "Sporting CP", "2026-10-13T16:45:00Z")]
    monkeypatch.setattr(client, "get_matches_by_date", fake_matches)
    kickoff = datetime(2026, 10, 13, 16, 45, tzinfo=timezone.utc)
    match = client.find_match("Racing Club de Lens", "Sporting Clube de Portugal", kickoff)
    assert match is not None and match["id"] == 42
    assert calls == ["2026-10-13"]


def test_fotmob_searches_adjacent_day_without_network(monkeypatch):
    client = FotMobClient()
    def fake_matches(date):
        if date == "2026-10-14":
            return [_fotmob_match("Lens", "Sporting CP", "2026-10-13T23:45:00Z")]
        return []
    monkeypatch.setattr(client, "get_matches_by_date", fake_matches)
    kickoff = datetime(2026, 10, 13, 23, 45, tzinfo=timezone.utc)
    assert client.find_match("Lens", "Sporting CP", kickoff)["id"] == 42


def test_fotmob_rejects_wrong_time_and_teams(monkeypatch):
    client = FotMobClient()
    monkeypatch.setattr(client, "get_matches_by_date", lambda date: [
        _fotmob_match("Lens", "Sporting CP", "2026-10-13T20:45:00Z"),
        _fotmob_match("Lens", "Sporting Braga", "2026-10-13T16:45:00Z"),
    ])
    kickoff = datetime(2026, 10, 13, 16, 45, tzinfo=timezone.utc)
    assert client.find_match("Lens", "Sporting CP", kickoff) is None


def test_api_football_rejects_wrong_time_without_network(monkeypatch):
    client = APIFootballClient(api_key="offline-test-key")
    monkeypatch.setattr(client, "get_fixtures_by_date", lambda date: [
        _api_fixture("Lens", "Sporting CP", "2026-10-13T20:45:00Z")
    ])
    kickoff = datetime(2026, 10, 13, 16, 45, tzinfo=timezone.utc)
    assert client.find_fixture("Lens", "Sporting CP", kickoff) is None


def test_api_football_accepts_correct_fixture_without_network(monkeypatch):
    client = APIFootballClient(api_key="offline-test-key")
    monkeypatch.setattr(client, "get_fixtures_by_date", lambda date: [
        _api_fixture("Lens", "Sporting CP", "2026-10-13T16:45:00Z")
    ])
    kickoff = datetime(2026, 10, 13, 16, 45, tzinfo=timezone.utc)
    assert client.find_fixture("Lens", "Sporting CP", kickoff)["fixture"]["id"] == 43
