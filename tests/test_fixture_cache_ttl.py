from datetime import datetime, timedelta, timezone

import pytest

from providers import competition_matches_ttl


NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def fixture(hours, status="TIMED"):
    kickoff = NOW + timedelta(hours=hours)
    return {
        "utcDate": kickoff.isoformat().replace("+00:00", "Z"),
        "status": status,
    }


@pytest.mark.parametrize(
    "hours, expected",
    [
        (48, 3600),
        (12, 900),
        (2, 900),
        (1, 240),
        (0.25, 240),
    ],
)
def test_scheduled_fixture_ttl(hours, expected):
    assert competition_matches_ttl(
        [fixture(hours)], NOW
    ) == expected


@pytest.mark.parametrize(
    "status",
    ["IN_PLAY", "PAUSED", "SUSPENDED", "POSTPONED"],
)
def test_critical_status_uses_short_ttl(status):
    assert competition_matches_ttl(
        [fixture(48, status)], NOW
    ) == 240


def test_nearest_fixture_determines_ttl():
    matches = [
        fixture(72),
        fixture(10),
        fixture(1),
    ]

    assert competition_matches_ttl(matches, NOW) == 240


def test_empty_fixture_list_uses_short_ttl():
    assert competition_matches_ttl([], NOW) == 240


def test_invalid_fixture_uses_short_ttl():
    assert competition_matches_ttl(
        [{"status": "TIMED", "utcDate": "invalid"}],
        NOW,
    ) == 240


def test_recently_finished_fixture_uses_short_ttl():
    assert competition_matches_ttl(
        [fixture(-3, "FINISHED")],
        NOW,
    ) == 240


def test_old_finished_fixture_allows_long_ttl():
    assert competition_matches_ttl(
        [fixture(-48, "FINISHED")],
        NOW,
    ) == 3600
