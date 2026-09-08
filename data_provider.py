from __future__ import annotations

import os
import unicodedata
from datetime import datetime, timedelta
from typing import Any

import requests

BASE_URL = "https://api.football-data.org/v4"
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"

COMPETITION_CODE = "CL"
REQUEST_TIMEOUT = 30
API_FOOTBALL_REQUEST_TIMEOUT = 30
API_FOOTBALL_CL_LEAGUE_ID = 2


class FootballDataError(RuntimeError):
    pass


class APIFootballError(RuntimeError):
    pass


def _normalize_team_name(value: str) -> str:
    value = value or ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char for char in value if not unicodedata.combining(char)
    )
    value = value.lower()

    replacements = {
        "fc": "",
        "cf": "",
        "afc": "",
        "sk": "",
        "ac": "",
        "calcio": "",
        "club": "",
        "football club": "",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    value = (
        value.replace("-", " ")
        .replace(".", " ")
        .replace(",", " ")
        .replace("'", " ")
        .replace('"', " ")
        .replace("/", " ")
    )

    return " ".join(value.split())


def _team_names_match(name_a: str, name_b: str) -> bool:
    a = _normalize_team_name(name_a)
    b = _normalize_team_name(name_b)

    if not a or not b:
        return False

    if a == b:
        return True

    if a in b or b in a:
        return True

    a_words = set(a.split())
    b_words = set(b.split())

    if len(a_words) >= 2 and len(b_words) >= 2:
        common = a_words & b_words
        if len(common) >= 2:
            return True

    return False


class FootballDataClient:
    """Rate-limit-conscious wrapper around football-data.org."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("FOOTBALL_DATA_API_KEY", "")
        if not self.api_key:
            raise FootballDataError("FOOTBALL_DATA_API_KEY eksik.")

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = requests.get(
            f"{BASE_URL}{path}",
            headers={"X-Auth-Token": self.api_key},
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:
            reset = response.headers.get("X-RequestCounter-Reset", "bilinmiyor")
            raise FootballDataError(
                f"football-data.org rate limit (429), reset={reset}s"
            )

        if response.status_code in {401, 403}:
            raise FootballDataError(
                f"football-data.org yetki hatası ({response.status_code})."
            )

        response.raise_for_status()
        return response.json()

    def get_matches(self) -> list[dict[str, Any]]:
        return self._get(f"/competitions/{COMPETITION_CODE}/matches").get(
            "matches", []
        )

    def get_match_details(self, match_id: int) -> dict[str, Any]:
        response = requests.get(
            f"{BASE_URL}/matches/{match_id}",
            headers={
                "X-Auth-Token": self.api_key,
                "X-Unfold-Lineups": "true",
                "X-Unfold-Bookings": "true",
                "X-Unfold-Subs": "true",
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:
            reset = response.headers.get("X-RequestCounter-Reset", "bilinmiyor")
            raise FootballDataError(
                f"football-data.org rate limit (429), reset={reset}s"
            )

        if response.status_code in {401, 403}:
            raise FootballDataError(
                f"football-data.org yetki hatası ({response.status_code})."
            )

        response.raise_for_status()
        return response.json()

    def get_standings(self) -> list[dict[str, Any]]:
        try:
            return self._get(
                f"/competitions/{COMPETITION_CODE}/standings"
            ).get("standings", [])
        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)
            if response is not None and response.status_code == 404:
                print(
                    "⚠️ football-data.org CL standings mevcut değil (404). "
                    "Standings atlanacak; analiz devam edecek."
                )
                return []
            raise

    def get_team_matches(
        self,
        team_id: int,
        before: datetime,
        days_back: int = 90,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        start = (before.date() - timedelta(days=days_back)).isoformat()
        end = before.date().isoformat()

        data = self._get(
            f"/teams/{team_id}/matches",
            params={
                "dateFrom": start,
                "dateTo": end,
                "status": "FINISHED",
                "limit": limit,
            },
        )

        matches = data.get("matches", [])
        matches.sort(key=lambda item: item.get("utcDate", ""), reverse=True)
        return matches[:limit]


class APIFootballClient:
    """
    API-Football ikinci veri kaynağı.
    Ana kullanım: resmi ilk 11, formation.
    Maç keşfi football-data.org üzerinden devam eder.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("API_FOOTBALL_KEY", "")
        if not self.api_key:
            raise APIFootballError("API_FOOTBALL_KEY eksik.")

        self._fixtures_cache: dict[str, list[dict[str, Any]]] = {}

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = requests.get(
            f"{API_FOOTBALL_BASE_URL}{path}",
            headers={"x-apisports-key": self.api_key},
            params=params or {},
            timeout=API_FOOTBALL_REQUEST_TIMEOUT,
        )

        if response.status_code == 429:
            raise APIFootballError("API-Football rate limit (429).")

        if response.status_code in {401, 403}:
            raise APIFootballError(
                f"API-Football yetki/API key hatası ({response.status_code})."
            )

        response.raise_for_status()
        data = response.json()

        errors = data.get("errors")
        if errors:
            if isinstance(errors, dict):
                error_text = "; ".join(
                    f"{key}: {value}" for key, value in errors.items()
                )
            else:
                error_text = str(errors)
            raise APIFootballError(f"API-Football API hatası: {error_text}")

        return data

    def get_fixtures_by_date(self, date: str) -> list[dict[str, Any]]:
        if date in self._fixtures_cache:
            return self._fixtures_cache[date]

        data = self._get(
            "/fixtures",
            params={
                "league": API_FOOTBALL_CL_LEAGUE_ID,
                "season": 2026,
                "date": date,
            },
        )

        fixtures = data.get("response", [])
        self._fixtures_cache[date] = fixtures
        return fixtures

    def find_fixture(
        self,
        home_team: str,
        away_team: str,
        kickoff: datetime,
    ) -> dict[str, Any] | None:
        fixtures = self.get_fixtures_by_date(kickoff.date().isoformat())

        best_match = None
        best_score = -1

        for fixture in fixtures:
            teams = fixture.get("teams", {})
            api_home = teams.get("home", {}).get("name", "")
            api_away = teams.get("away", {}).get("name", "")

            if not api_home or not api_away:
                continue

            home_match = _team_names_match(home_team, api_home)
            away_match = _team_names_match(away_team, api_away)

            if not home_match or not away_match:
                continue

            score = 0
            if home_match:
                score += 10
            if away_match:
                score += 10

            fixture_date = fixture.get("fixture", {}).get("date")
            if fixture_date:
                try:
                    fixture_dt = datetime.fromisoformat(
                        fixture_date.replace("Z", "+00:00")
                    )
                    diff_minutes = abs(
                        (fixture_dt - kickoff).total_seconds() / 60
                    )
                    if diff_minutes <= 30:
                        score += 10
                    elif diff_minutes <= 120:
                        score += 5
                except ValueError:
                    pass

            if score > best_score:
                best_score = score
                best_match = fixture

        return best_match

    def get_lineups(self, fixture_id: int) -> list[dict[str, Any]]:
        data = self._get(
            "/fixtures/lineups",
            params={"fixture": fixture_id},
        )
        return data.get("response", [])

    def get_match_official_xi(
        self,
        home_team: str,
        away_team: str,
        kickoff_utc: datetime,
    ) -> dict[str, Any] | None:
        fixture = self.find_fixture(home_team, away_team, kickoff_utc)

        if not fixture:
            print(
                f"⚠️ API-Football fixture bulunamadı: {home_team} - {away_team}"
            )
            return None

        fixture_data = fixture.get("fixture", {})
        fixture_id = fixture_data.get("id")
        if fixture_id is None:
            return None

        lineups = self.get_lineups(int(fixture_id))

        home_api_name = (
            fixture.get("teams", {}).get("home", {}).get("name", home_team)
        )
        away_api_name = (
            fixture.get("teams", {}).get("away", {}).get("name", away_team)
        )

        home_xi: list[dict[str, Any]] = []
        away_xi: list[dict[str, Any]] = []
        home_formation = None
        away_formation = None

        for lineup in lineups:
            team = lineup.get("team", {})
            team_id = team.get("id")
            team_name = team.get("name", "")

            start_xi = lineup.get("startXI") or []
            players = []

            for item in start_xi:
                player = item.get("player", {})
                players.append(
                    {
                        "id": player.get("id"),
                        "name": player.get("name"),
                        "number": player.get("number"),
                        "pos": player.get("pos"),
                        "grid": player.get("grid"),
                    }
                )

            if _team_names_match(team_name, home_api_name):
                home_xi = players
                home_formation = lineup.get("formation")
            elif _team_names_match(team_name, away_api_name):
                away_xi = players
                away_formation = lineup.get("formation")
            elif team_id == (
                fixture.get("teams", {}).get("home", {}).get("id")
            ):
                home_xi = players
                home_formation = lineup.get("formation")
            elif team_id == (
                fixture.get("teams", {}).get("away", {}).get("id")
            ):
                away_xi = players
                away_formation = lineup.get("formation")

        if len(home_xi) >= 11 and len(away_xi) >= 11:
            return {
                "status": "ANNOUNCED",
                "home": home_xi,
                "away": away_xi,
                "home_formation": home_formation,
                "away_formation": away_formation,
                "source": "API-Football",
                "fixture_id": fixture_id,
            }

        print(
            f"⏳ API-Football XI henüz tam değil: "
            f"{home_team} - {away_team} "
            f"({len(home_xi)}/11 - {len(away_xi)}/11)"
        )
        return None


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_team_form(
    matches: list[dict[str, Any]],
    team_id: int,
    last_n: int = 5,
) -> dict[str, Any]:
    finished = []

    for match in matches:
        score = match.get("score", {}).get("fullTime", {})
        home = score.get("home")
        away = score.get("away")

        if home is None or away is None:
            continue

        is_home = match.get("homeTeam", {}).get("id") == team_id

        gf = home if is_home else away
        ga = away if is_home else home

        points = 3 if gf > ga else 1 if gf == ga else 0
        result = "W" if gf > ga else "D" if gf == ga else "L"

        finished.append(
            {
                "date": match.get("utcDate"),
                "competition": match.get("competition", {}).get("name"),
                "opponent": (
                    match.get("awayTeam", {}).get("name")
                    if is_home
                    else match.get("homeTeam", {}).get("name")
                ),
                "venue": "HOME" if is_home else "AWAY",
                "goals_for": gf,
                "goals_against": ga,
                "result": result,
                "points": points,
            }
        )

    finished = finished[:last_n]

    goals_for = sum(item["goals_for"] for item in finished)
    goals_against = sum(item["goals_against"] for item in finished)
    points = sum(item["points"] for item in finished)

    return {
        "matches": finished,
        "last_5": "-".join(item["result"] for item in finished) or "N/A",
        "points_last_5": points,
        "goals_for_last_5": goals_for,
        "goals_against_last_5": goals_against,
        "avg_goals_for": (
            round(goals_for / len(finished), 2) if finished else None
        ),
        "avg_goals_against": (
            round(goals_against / len(finished), 2) if finished else None
        ),
    }
