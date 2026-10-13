from __future__ import annotations

import os
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

BASE_URL = "https://api.football-data.org/v4"
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"

COMPETITION_CODE = "CL"
REQUEST_TIMEOUT = 30
API_FOOTBALL_REQUEST_TIMEOUT = 12
API_FOOTBALL_CL_LEAGUE_ID = 2
FOTMOB_BASE_URL = "https://www.fotmob.com/api/data"
FOTMOB_REQUEST_TIMEOUT = 12


class FootballDataError(RuntimeError):
    pass


class APIFootballError(RuntimeError):
    pass


# Only remove complete club-designator words; never substrings inside names.
_CLUB_WORDS = {"fc", "cf", "afc", "sk", "fk", "ac", "club", "football", "calcio"}
_TEAM_ALIASES = {
    "racing de lens": "lens",
    "racing club de lens": "lens",
    "rc lens": "lens",
    "sporting clube de portugal": "sporting portugal",
    "sporting cp": "sporting portugal",
    "sporting lisbon": "sporting portugal",
    # Conservative known-name variants for the seven 22:00 fixtures.
    # Aliases still require matching *both* teams and kickoff time.
    "internazionale milano": "inter",
    "internazionale": "inter",
    "inter milan": "inter",
    "inter milano": "inter",
    "brugge kv": "brugge",
    "brugge": "brugge",
    "atletico de madrid": "atletico madrid",
    "atletico madrid": "atletico madrid",
    "bayern munchen": "bayern munich",
    "bayern munich": "bayern munich",
    "psv eindhoven": "psv",
    "psv": "psv",
    "ssc napoli": "napoli",
    "napoli": "napoli",
    "lille osc": "lille",
    "lille": "lille",
    "rb leipzig": "leipzig",
    "rasenballsport leipzig": "leipzig",
    "leipzig": "leipzig",
}


def _normalize_team_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c)).casefold()
    import re
    words = re.findall(r"[a-z0-9]+", value)
    normalized = " ".join(w for w in words if w not in _CLUB_WORDS)
    return _TEAM_ALIASES.get(normalized, normalized)


def _team_names_match(name_a: str, name_b: str) -> bool:
    a, b = _normalize_team_name(name_a), _normalize_team_name(name_b)
    if not a or not b:
        return False
    if a == b:
        return True
    # Do not accept arbitrary substrings or generic shared words.
    a_words, b_words = set(a.split()), set(b.split())
    return (len(a_words) >= 2 and len(b_words) >= 2
            and len(a_words & b_words) >= 2
            and (len(a_words & b_words) / max(len(a_words), len(b_words))) >= 0.75)


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


class FotMobError(RuntimeError):
    pass


class FotMobClient:
    """FotMob fallback for confirmed starting XIs. No API key required."""

    def __init__(self) -> None:
        self._matches_cache: dict[str, list[dict[str, Any]]] = {}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.get(
            f"{FOTMOB_BASE_URL}{path}",
            params=params or {},
            headers={"User-Agent": "Mozilla/5.0 (compatible; CLTahmin/2026)"},
            timeout=FOTMOB_REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise FotMobError(f"FotMob HTTP hatası ({response.status_code}).")
        try:
            return response.json()
        except ValueError as error:
            raise FotMobError("FotMob JSON yanıtı okunamadı.") from error

    def get_matches_by_date(self, date: str) -> list[dict[str, Any]]:
        if date in self._matches_cache:
            return self._matches_cache[date]
        data = self._get("/matches", params={"date": date.replace("-", "")})
        matches: list[dict[str, Any]] = []
        for league in data.get("leagues", []) or []:
            matches.extend(league.get("matches", []) or [])
        self._matches_cache[date] = matches
        return matches

    def find_match(
        self,
        home_team: str,
        away_team: str,
        kickoff_utc: datetime,
    ) -> dict[str, Any] | None:
        # FotMob groups fixtures by calendar day; UTC/local boundaries can differ.
        # Query neighbouring days only if the kickoff day's search finds no match.
        if kickoff_utc.tzinfo is None:
            kickoff_utc = kickoff_utc.replace(tzinfo=timezone.utc)
        kickoff_utc = kickoff_utc.astimezone(timezone.utc)
        best_match = None
        best_diff = float("inf")
        for offset in (0, -1, 1):
            date = (kickoff_utc.date() + timedelta(days=offset)).isoformat()
            matches = self.get_matches_by_date(date)
            for match in matches:
                home_name = (match.get("home") or {}).get("name", "")
                away_name = (match.get("away") or {}).get("name", "")
                if not (_team_names_match(home_team, home_name)
                        and _team_names_match(away_team, away_name)):
                    continue
                utc_value = (match.get("status") or {}).get("utcTime")
                if not utc_value:
                    continue
                try:
                    match_dt = datetime.fromisoformat(utc_value.replace("Z", "+00:00"))
                    if match_dt.tzinfo is None:
                        continue
                    diff = abs((match_dt.astimezone(timezone.utc) - kickoff_utc).total_seconds())
                except (TypeError, ValueError):
                    continue
                if diff <= 90 * 60 and diff < best_diff:
                    best_match, best_diff = match, diff
            if best_match is not None:
                break
        return best_match

    @staticmethod
    def _normalize_players(raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, dict):
            raw = raw.get("players") or raw.get("starters") or []
        result: list[dict[str, Any]] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            player = item.get("player") if isinstance(item.get("player"), dict) else item
            name = player.get("name") or player.get("playerName")
            if not name:
                continue
            result.append({
                "id": player.get("id") or player.get("playerId"),
                "name": name,
                "number": player.get("shirtNumber") or player.get("number"),
                "pos": player.get("position") or player.get("positionId") or player.get("pos"),
                "grid": player.get("grid"),
            })
        return result

    def _extract_lineup_teams(self, data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        content = data.get("content") if isinstance(data.get("content"), dict) else data
        lineup = content.get("lineup") if isinstance(content, dict) else None
        if not isinstance(lineup, dict):
            return {}, {}

        # Current FotMob matchDetails payload: content.lineup.lineups[]
        teams = lineup.get("lineups")
        if isinstance(teams, list):
            home: dict[str, Any] = {}
            away: dict[str, Any] = {}
            for team in teams:
                if not isinstance(team, dict):
                    continue
                team_id = str(team.get("teamId", ""))
                if not home:
                    home = team
                elif team_id != str(home.get("teamId", "")):
                    away = team
                    break
            return home, away

        # Compatibility with payloads exposing homeTeam / awayTeam directly.
        home = lineup.get("homeTeam") if isinstance(lineup.get("homeTeam"), dict) else {}
        away = lineup.get("awayTeam") if isinstance(lineup.get("awayTeam"), dict) else {}
        return home, away

    def get_match_official_xi(
        self,
        home_team: str,
        away_team: str,
        kickoff_utc: datetime,
    ) -> dict[str, Any] | None:
        match = self.find_match(home_team, away_team, kickoff_utc)
        if not match:
            print(f"⚠️ FotMob maçı bulunamadı: {home_team} - {away_team}")
            return None

        match_id = match.get("id")
        if match_id is None:
            return None

        data = self._get("/matchDetails", params={"matchId": match_id})
        lineup = (data.get("content") or {}).get("lineup") or {}
        if lineup.get("confirmed") is not True:
            return None
        home, away = self._extract_lineup_teams(data)
        expected_home = str((match.get("home") or {}).get("id", ""))
        expected_away = str((match.get("away") or {}).get("id", ""))
        by_id = {str(x.get("teamId", x.get("id", ""))): x for x in (home, away)}
        if not expected_home or not expected_away or expected_home not in by_id or expected_away not in by_id:
            return None
        home, away = by_id[expected_home], by_id[expected_away]
        home_xi = self._normalize_players(home.get("players") or home.get("starters") or [])
        away_xi = self._normalize_players(away.get("players") or away.get("starters") or [])

        if len(home_xi) >= 11 and len(away_xi) >= 11:
            return {
                "status": "ANNOUNCED",
                "home": home_xi[:11],
                "away": away_xi[:11],
                "home_formation": home.get("formation"),
                "away_formation": away.get("formation"),
                "source": "FotMob",
                "match_id": match_id,
            }

        print(
            f"⏳ FotMob XI henüz tam değil: {home_team} - {away_team} "
            f"({len(home_xi)}/11 - {len(away_xi)}/11)"
        )
        return None


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
                "season": int(os.getenv("SEASON_START", "2026")),
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
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)
        kickoff = kickoff.astimezone(timezone.utc)
        best_match = None
        best_diff = float("inf")
        for offset in (0, -1, 1):
            date = (kickoff.date() + timedelta(days=offset)).isoformat()
            fixtures = self.get_fixtures_by_date(date)
            for fixture in fixtures:
                teams = fixture.get("teams") or {}
                api_home = (teams.get("home") or {}).get("name", "")
                api_away = (teams.get("away") or {}).get("name", "")
                if not (_team_names_match(home_team, api_home)
                        and _team_names_match(away_team, api_away)):
                    continue
                fixture_date = (fixture.get("fixture") or {}).get("date")
                if not fixture_date:
                    continue
                try:
                    fixture_dt = datetime.fromisoformat(fixture_date.replace("Z", "+00:00"))
                    if fixture_dt.tzinfo is None:
                        continue
                    diff = abs((fixture_dt.astimezone(timezone.utc) - kickoff).total_seconds())
                except (TypeError, ValueError):
                    continue
                if diff <= 120 * 60 and diff < best_diff:
                    best_match, best_diff = fixture, diff
            if best_match is not None:
                break
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