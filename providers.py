"""Cached football data and conservative lineup verification."""

import os
import time
from datetime import datetime, timezone

import requests

from data_provider import (
    BASE_URL,
    FootballDataClient,
    FootballDataError,
    APIFootballClient,
    FotMobClient,
)
from learning import digest


# ---------------------------------------------------------------------------
# Dynamic Champions League fixture cache
# ---------------------------------------------------------------------------

SHORT_TTL = 240
MEDIUM_TTL = 900
LONG_TTL = 3600

CACHE_MAX_AGE = 86400

ACTIVE_MATCH_STATUSES = {
    "IN_PLAY",
    "PAUSED",
    "LIVE",
    "SUSPENDED",
}

COMPLETED_MATCH_STATUSES = {
    "FINISHED",
    "AWARDED",
}

def competition_matches_ttl(matches, now=None):
    """
    Determine a conservative TTL for the Champions League fixture list.

    - Active, postponed or uncertain fixtures: 240 seconds
    - Kickoff within 90 minutes: 240 seconds
    - Kickoff within 24 hours: 900 seconds
    - No nearby fixtures: 3600 seconds

    Recently completed matches remain on the short TTL to allow
    results and status changes to propagate.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if not isinstance(matches, list):
        return SHORT_TTL

    # An empty or malformed fixture list should not be cached for an hour.
    if not matches:
        return SHORT_TTL

    result_ttl = LONG_TTL

    for match in matches:
        if not isinstance(match, dict):
            return SHORT_TTL

        status = str(match.get("status") or "").upper()

        if status in ACTIVE_MATCH_STATUSES:
            return SHORT_TTL

        try:
            utc_date = match["utcDate"]

            if not isinstance(utc_date, str):
                return SHORT_TTL

            kickoff = datetime.fromisoformat(
                utc_date.replace("Z", "+00:00")
            )

            if kickoff.tzinfo is None:
                return SHORT_TTL

            kickoff = kickoff.astimezone(timezone.utc)

        except (KeyError, TypeError, ValueError, AttributeError):
            return SHORT_TTL

        hours_until = (kickoff - now).total_seconds() / 3600

        if status in {"POSTPONED", "CANCELLED"}:
            if hours_until >= -24:
                return SHORT_TTL
            continue

        if status in COMPLETED_MATCH_STATUSES:
            # Recently completed fixtures may still receive corrections.
            if -6 <= hours_until <= 0:
                return SHORT_TTL
            continue

        # Unknown match statuses are treated conservatively.
        if status not in {"SCHEDULED", "TIMED"}:
            return SHORT_TTL

        # Match recently started, or kickoff is within 90 minutes.
        if -6 <= hours_until <= 1.5:
            return SHORT_TTL

        # Match is approaching within the next 24 hours.
        if 1.5 < hours_until <= 24:
            result_ttl = min(result_ttl, MEDIUM_TTL)

    return result_ttl


def _valid_cache_entry(entry):
    """Validate a persisted cache entry before using it."""
    if not isinstance(entry, dict):
        return False

    timestamp = entry.get("at")
    data = entry.get("data")

    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return False

    if not isinstance(data, dict):
        return False

    return True


class CachedFootball(FootballDataClient):
    def __init__(self, cache, save):
        super().__init__()
        self.cache, self.save = cache, save
        self.last_call = 0

    def _get(self, path, params=None):
        key = digest([path, params or {}])
        now = time.time()

        is_competition_matches = (
            path.endswith("/matches")
            and "/competitions/" in path
        )

        # Default TTL for non-fixture endpoints.
        ttl = LONG_TTL

        # Match details and official lineups need frequent refreshes.
        if path.startswith("/matches/"):
            ttl = SHORT_TTL

        entry = self.cache.get(key)

        if _valid_cache_entry(entry):
            age = now - entry["at"]

            if is_competition_matches:
                matches = entry["data"].get("matches")

                # Calculate TTL from cached fixtures, not from a new API call.
                ttl = competition_matches_ttl(
                    matches,
                    now=datetime.fromtimestamp(now, timezone.utc),
                )

                # A fixture approaching kickoff must not remain cached
                # beyond the point where the shorter TTL is required.
                if isinstance(matches, list):
                    for match in matches:
                        if not isinstance(match, dict):
                            ttl = SHORT_TTL
                            break

                        try:
                            kickoff = datetime.fromisoformat(
                                match["utcDate"].replace("Z", "+00:00")
                            )

                            if kickoff.tzinfo is None:
                                ttl = SHORT_TTL
                                break

                            kickoff = kickoff.astimezone(timezone.utc)

                        except (KeyError, TypeError, ValueError, AttributeError):
                            ttl = SHORT_TTL
                            break

                        seconds_until = (
                            kickoff - datetime.fromtimestamp(
                                now, timezone.utc
                            )
                        ).total_seconds()

                        if 0 < seconds_until <= 90 * 60:
                            ttl = SHORT_TTL
                            break

            if 0 <= age < ttl:
                return entry["data"]

        # Preserve existing request spacing.
        time.sleep(
            max(
                0,
                6.2 - (time.monotonic() - self.last_call),
            )
        )
        self.last_call = time.monotonic()

        try:
            response = requests.get(
                f"{BASE_URL}{path}",
                headers={
                    "X-Auth-Token": self.api_key,
                    "X-Unfold-Lineups": "true",
                },
                params=params or {},
                timeout=15,
            )

            if response.status_code == 429:
                raise FootballDataError(
                    "football-data API rate limit (429)"
                )

            if response.status_code != 200:
                raise FootballDataError(
                    f"football-data HTTP {response.status_code}"
                )

            data = response.json()

            if not isinstance(data, dict):
                raise FootballDataError(
                    "football-data JSON şeması geçersiz"
                )

        except requests.RequestException:
            raise FootballDataError(
                "football-data bağlantı hatası"
            ) from None

        except ValueError:
            raise FootballDataError(
                "football-data JSON hatası"
            ) from None

        self.cache[key] = {
            "at": time.time(),
            "data": data,
        }

        # Remove obsolete or invalid snapshots.
        for old in list(self.cache):
            old_entry = self.cache.get(old)

            if not _valid_cache_entry(old_entry):
                del self.cache[old]
                continue

            age = now - old_entry["at"]

            if age > CACHE_MAX_AGE or age < 0:
                del self.cache[old]

        self.save()

        return data

    def get_matches(self):
        year = int(os.getenv("SEASON_START", "2026"))

        return self._get(
            "/competitions/CL/matches",
            {"season": year},
        ).get("matches", [])

    def get_match_details(self, match_id):
        return self._get(f"/matches/{match_id}")

    def get_team_matches(self, team_id, before, **kwargs):
        rows = super().get_team_matches(
            team_id,
            before,
            **kwargs,
        )

        return [
            r
            for r in rows
            if r.get("status") == "FINISHED"
            and datetime.fromisoformat(
                r["utcDate"].replace("Z", "+00:00")
            ) < before
        ]


# ---------------------------------------------------------------------------
# Official starting XI verification
# ---------------------------------------------------------------------------

def valid_xi(players):
    return (
        isinstance(players, list)
        and len(players) == 11
        and all(
            isinstance(p, dict) and p.get("name")
            for p in players
        )
        and len({
            p["name"].casefold()
            for p in players
        }) == 11
    )


def official_xi(football, match):
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]

    kickoff = datetime.fromisoformat(
        match["utcDate"].replace("Z", "+00:00")
    )

    try:
        details = football.get_match_details(match["id"])

        # football-data v4 stores lineups inside team objects.
        h = (details.get("homeTeam") or {}).get("lineup")
        a = (details.get("awayTeam") or {}).get("lineup")

        if valid_xi(h) and valid_xi(a):
            return {
                "status": "ANNOUNCED",
                "home": h,
                "away": a,
                "source": "football-data.org",
                "checked_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            }

    except FootballDataError:
        pass

    clients = []

    if os.getenv("API_FOOTBALL_KEY"):
        clients.append(APIFootballClient)

    clients.append(FotMobClient)

    for factory in clients:
        try:
            xi = factory().get_match_official_xi(
                home,
                away,
                kickoff,
            )

            if (
                xi
                and valid_xi(xi.get("home"))
                and valid_xi(xi.get("away"))
            ):
                xi["checked_at"] = datetime.now(
                    timezone.utc
                ).isoformat()

                return xi

        except Exception:
            # External fallback failures must not interrupt match processing.
            pass

    return None


# ---------------------------------------------------------------------------
# Predicted starting XI verification
# ---------------------------------------------------------------------------

def predicted_xi(research):
    """
    Only include players with confirmed club eligibility,
    availability checks and a secure source URL.
    """
    result = {
        "status": "PREDICTED",
        "home": [],
        "away": [],
    }

    for side in ("home", "away"):
        players = (
            (research.get("predicted_xi") or {}).get(side)
            or []
        )

        names = set()

        for p in players if isinstance(players, list) else []:
            if not isinstance(p, dict):
                continue

            name = str(
                p.get("name", "")
            ).strip()

            if (
                name
                and name.casefold() not in names
                and p.get("current_club_confirmed") is True
                and p.get("unavailable") is False
                and str(
                    p.get("source_url", "")
                ).startswith("https://")
            ):
                result[side].append(p)
                names.add(name.casefold())

        result[side] = result[side][:11]

    return result
