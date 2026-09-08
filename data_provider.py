from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import requests


# ============================================================
# FOOTBALL-DATA.ORG
# ============================================================

BASE_URL = "https://api.football-data.org/v4"
COMPETITION_CODE = "CL"


# ============================================================
# API-FOOTBALL
# ============================================================

API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"


REQUEST_TIMEOUT = 30


class FootballDataError(RuntimeError):
    pass


class FootballDataClient:
    """
    Football data sağlayıcısı.

    Birinci kaynak:
        football-data.org

    İkinci kaynak:
        API-Football

    API-Football özellikle resmi ilk 11 kontrolünde
    yedek kaynak olarak kullanılabilir.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_football_key: str | None = None,
    ) -> None:

        self.api_key = (
            api_key
            or os.environ.get(
                "FOOTBALL_DATA_API_KEY",
                "",
            )
        )

        self.api_football_key = (
            api_football_key
            or os.environ.get(
                "API_FOOTBALL_KEY",
                "",
            )
        )

        if not self.api_key:
            raise FootballDataError(
                "FOOTBALL_DATA_API_KEY eksik."
            )

    # ========================================================
    # FOOTBALL-DATA.ORG REQUEST
    # ========================================================

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        response = requests.get(
            f"{BASE_URL}{path}",
            headers={
                "X-Auth-Token": self.api_key,
            },
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:

            reset = response.headers.get(
                "X-RequestCounter-Reset",
                "bilinmiyor",
            )

            raise FootballDataError(
                "football-data.org rate limit "
                f"(429), reset={reset}s"
            )

        if response.status_code in {
            401,
            403,
        }:

            raise FootballDataError(
                "football-data.org yetki hatası "
                f"({response.status_code})."
            )

        response.raise_for_status()

        return response.json()

    # ========================================================
    # FOOTBALL-DATA.ORG MATCHES
    # ========================================================

    def get_matches(
        self,
    ) -> list[dict[str, Any]]:

        return self._get(
            f"/competitions/{COMPETITION_CODE}/matches"
        ).get(
            "matches",
            [],
        )

    # ========================================================
    # FOOTBALL-DATA.ORG MATCH DETAILS
    # ========================================================

    def get_match_details(
        self,
        match_id: int,
    ) -> dict[str, Any]:

        """
        Football-data.org maç detayları.

        Lineup bilgisi sağlayıcı tarafından mevcutsa
        X-Unfold-Lineups ile istenir.
        """

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

            reset = response.headers.get(
                "X-RequestCounter-Reset",
                "bilinmiyor",
            )

            raise FootballDataError(
                "football-data.org rate limit "
                f"(429), reset={reset}s"
            )

        if response.status_code in {
            401,
            403,
        }:

            raise FootballDataError(
                "football-data.org yetki hatası "
                f"({response.status_code})."
            )

        response.raise_for_status()

        return response.json()

    # ========================================================
    # API-FOOTBALL REQUEST
    # ========================================================

    def _api_football_get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        if not self.api_football_key:

            raise FootballDataError(
                "API_FOOTBALL_KEY tanımlı değil."
            )

        response = requests.get(
            f"{API_FOOTBALL_BASE_URL}{path}",
            headers={
                "x-apisports-key":
                    self.api_football_key,
            },
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:

            raise FootballDataError(
                "API-Football rate limit (429)."
            )

        if response.status_code in {
            401,
            403,
        }:

            raise FootballDataError(
                "API-Football yetki hatası "
                f"({response.status_code})."
            )

        response.raise_for_status()

        data = response.json()

        errors = data.get(
            "errors"
        )

        if errors:

            raise FootballDataError(
                "API-Football API hatası: "
                f"{errors}"
            )

        return data

    # ========================================================
    # API-FOOTBALL MAÇ ARAMA
    # ========================================================

    def find_api_football_fixture(
        self,
        home_team: str,
        away_team: str,
        match_utc: datetime,
    ) -> dict[str, Any] | None:

        """
        API-Football üzerinde maçı bulur.

        Önce tarih üzerinden fixture listesi alınır.
        Ardından takım isimleri mümkün olduğunca
        eşleştirilir.
        """

        if not self.api_football_key:

            print(
                "ℹ️ API_FOOTBALL_KEY yok; "
                "API-Football ikinci kaynak "
                "kullanılmayacak."
            )

            return None

        date_string = (
            match_utc.date().isoformat()
        )

        try:

            data = self._api_football_get(
                "/fixtures",
                {
                    "date": date_string,
                },
            )

        except FootballDataError as error:

            print(
                f"⚠️ API-Football fixture araması "
                f"başarısız: {error}"
            )

            return None

        fixtures = data.get(
            "response",
            [],
        )

        home_normalized = (
            self._normalize_team_name(
                home_team
            )
        )

        away_normalized = (
            self._normalize_team_name(
                away_team
            )
        )

        best_match = None
        best_score = 0

        for fixture in fixtures:

            teams = fixture.get(
                "teams",
                {},
            )

            fixture_home = (
                teams.get(
                    "home",
                    {},
                ).get(
                    "name",
                    "",
                )
            )

            fixture_away = (
                teams.get(
                    "away",
                    {},
                ).get(
                    "name",
                    "",
                )
            )

            fixture_home_normalized = (
                self._normalize_team_name(
                    fixture_home
                )
            )

            fixture_away_normalized = (
                self._normalize_team_name(
                    fixture_away
                )
            )

            score = 0

            if (
                home_normalized
                == fixture_home_normalized
            ):
                score += 2

            elif (
                home_normalized
                in fixture_home_normalized
                or fixture_home_normalized
                in home_normalized
            ):
                score += 1

            if (
                away_normalized
                == fixture_away_normalized
            ):
                score += 2

            elif (
                away_normalized
                in fixture_away_normalized
                or fixture_away_normalized
                in away_normalized
            ):
                score += 1

            if score > best_score:

                best_score = score
                best_match = fixture

        if best_match and best_score >= 3:

            return best_match

        print(
            f"⚠️ API-Football'da eşleşen maç "
            f"bulunamadı: "
            f"{home_team} - {away_team}"
        )

        return None

    # ========================================================
    # API-FOOTBALL RESMİ XI
    # ========================================================

    def get_api_football_lineups(
        self,
        home_team: str,
        away_team: str,
        match_utc: datetime,
    ) -> dict[str, Any] | None:

        """
        API-Football üzerinden resmi ilk 11'i alır.

        Dönen yapı:

        {
            "status": "ANNOUNCED",
            "home": [...],
            "away": [...],
            "source": "API-Football",
            "fixture_id": ...
        }

        XI henüz açıklanmamışsa None döner.
        """

        if not self.api_football_key:

            return None

        fixture = (
            self.find_api_football_fixture(
                home_team,
                away_team,
                match_utc,
            )
        )

        if not fixture:

            return None

        fixture_id = (
            fixture.get(
                "fixture",
                {},
            ).get(
                "id"
            )
        )

        if not fixture_id:

            return None

        try:

            data = self._api_football_get(
                "/fixtures/lineups",
                {
                    "fixture": fixture_id,
                },
            )

        except FootballDataError as error:

            print(
                f"⚠️ API-Football XI alınamadı: "
                f"{error}"
            )

            return None

        lineups = data.get(
            "response",
            [],
        )

        if not lineups:

            print(
                f"⏳ API-Football: "
                f"{home_team} - {away_team} "
                f"için resmi XI henüz yok."
            )

            return None

        home_lineup = None
        away_lineup = None

        for lineup in lineups:

            team = lineup.get(
                "team",
                {},
            )

            team_name = self._normalize_team_name(
                team.get(
                    "name",
                    "",
                )
            )

            if (
                team_name
                == self._normalize_team_name(
                    home_team
                )
                or self._team_names_similar(
                    team_name,
                    home_team,
                )
            ):

                home_lineup = lineup

            elif (
                team_name
                == self._normalize_team_name(
                    away_team
                )
                or self._team_names_similar(
                    team_name,
                    away_team,
                )
            ):

                away_lineup = lineup

        if not home_lineup or not away_lineup:

            print(
                f"⚠️ API-Football XI bulundu fakat "
                f"takım eşleşmesi tamamlanamadı: "
                f"{home_team} - {away_team}"
            )

            return None

        home_start_xi = [
            player
            for player in home_lineup.get(
                "startXI",
                [],
            )
            if player.get("player")
        ]

        away_start_xi = [
            player
            for player in away_lineup.get(
                "startXI",
                [],
            )
            if player.get("player")
        ]

        if (
            len(home_start_xi) < 11
            or len(away_start_xi) < 11
        ):

            print(
                f"⏳ API-Football resmi XI "
                f"henüz tam değil: "
                f"{len(home_start_xi)}/11 - "
                f"{len(away_start_xi)}/11"
            )

            return None

        print(
            f"✅ API-Football resmi XI doğrulandı: "
            f"{home_team} - {away_team}"
        )

        return {
            "status": "ANNOUNCED",
            "home": home_start_xi,
            "away": away_start_xi,
            "source": "API-Football",
            "fixture_id": fixture_id,
        }

    # ========================================================
    # TAKIM İSMİ NORMALİZASYONU
    # ========================================================

    @staticmethod
    def _normalize_team_name(
        value: str,
    ) -> str:

        value = (
            value
            .lower()
            .strip()
        )

        replacements = {
            "fc": "",
            "cf": "",
            "afc": "",
            "fk": "",
            "sk": "",
            "real madrid cf": "real madrid",
            "fc internazionale milano":
                "inter milan",
            "internazionale":
                "inter milan",
            "inter": "inter milan",
            "borussia dortmund":
                "dortmund",
            "villarreal cf":
                "villarreal",
            "lille osc":
                "lille",
            "real betis balompie":
                "real betis",
            "manchester city fc":
                "manchester city",
            "fc porto":
                "porto",
        }

        for old, new in replacements.items():

            if value == old:
                value = new

        return (
            " ".join(
                value.split()
            )
        )

    @classmethod
    def _team_names_similar(
        cls,
        first: str,
        second: str,
    ) -> bool:

        first_normalized = (
            cls._normalize_team_name(
                first
            )
        )

        second_normalized = (
            cls._normalize_team_name(
                second
            )
        )

        if (
            first_normalized
            == second_normalized
        ):
            return True

        first_words = set(
            first_normalized.split()
        )

        second_words = set(
            second_normalized.split()
        )

        if not first_words or not second_words:
            return False

        overlap = (
            first_words
            & second_words
        )

        return bool(overlap)

    # ========================================================
    # STANDINGS
    # ========================================================

    def get_standings(
        self,
    ) -> list[dict[str, Any]]:

        """
        CL standings football-data.org'da
        bulunamazsa boş döner.
        """

        try:

            return self._get(
                f"/competitions/"
                f"{COMPETITION_CODE}/standings"
            ).get(
                "standings",
                [],
            )

        except requests.HTTPError as exc:

            response = getattr(
                exc,
                "response",
                None,
            )

            if (
                response is not None
                and response.status_code == 404
            ):

                print(
                    "⚠️ football-data.org CL "
                    "standings mevcut değil (404). "
                    "Standings atlanacak; "
                    "analiz devam edecek."
                )

                return []

            raise

    # ========================================================
    # TAKIM MAÇLARI
    # ========================================================

    def get_team_matches(
        self,
        team_id: int,
        before: datetime,
        days_back: int = 90,
        limit: int = 20,
    ) -> list[dict[str, Any]]:

        start = (
            before.date()
            - timedelta(
                days=days_back
            )
        ).isoformat()

        end = (
            before.date()
            .isoformat()
        )

        data = self._get(
            f"/teams/{team_id}/matches",
            params={
                "dateFrom": start,
                "dateTo": end,
                "status": "FINISHED",
                "limit": limit,
            },
        )

        matches = data.get(
            "matches",
            [],
        )

        matches.sort(
            key=lambda item:
                item.get(
                    "utcDate",
                    "",
                ),
            reverse=True,
        )

        return matches[:limit]


# ============================================================
# UTC PARSE
# ============================================================

def parse_utc(
    value: str,
) -> datetime:

    return datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    )


# ============================================================
# TAKIM FORMU
# ============================================================

def build_team_form(
    matches: list[dict[str, Any]],
    team_id: int,
    last_n: int = 5,
) -> dict[str, Any]:

    finished = []

    for match in matches:

        score = (
            match.get(
                "score",
                {},
            ).get(
                "fullTime",
                {},
            )
        )

        home = score.get(
            "home"
        )

        away = score.get(
            "away"
        )

        if (
            home is None
            or away is None
        ):
            continue

        is_home = (
            match.get(
                "homeTeam",
                {},
            ).get(
                "id"
            )
            == team_id
        )

        gf = (
            home
            if is_home
            else away
        )

        ga = (
            away
            if is_home
            else home
        )

        points = (
            3
            if gf > ga
            else 1
            if gf == ga
            else 0
        )

        result = (
            "W"
            if gf > ga
            else "D"
            if gf == ga
            else "L"
        )

        finished.append(
            {
                "date": match.get(
                    "utcDate"
                ),
                "competition": (
                    match.get(
                        "competition",
                        {},
                    ).get(
                        "name"
                    )
                ),
                "opponent": (
                    match.get(
                        "awayTeam",
                        {},
                    ).get(
                        "name"
                    )
                    if is_home
                    else match.get(
                        "homeTeam",
                        {},
                    ).get(
                        "name"
                    )
                ),
                "venue": (
                    "HOME"
                    if is_home
                    else "AWAY"
                ),
                "goals_for": gf,
                "goals_against": ga,
                "result": result,
                "points": points,
            }
        )

    finished = finished[:last_n]

    goals_for = sum(
        item["goals_for"]
        for item in finished
    )

    goals_against = sum(
        item["goals_against"]
        for item in finished
    )

    points = sum(
        item["points"]
        for item in finished
    )

    return {
        "matches": finished,
        "last_5": (
            "-".join(
                item["result"]
                for item in finished
            )
            or "N/A"
        ),
        "points_last_5": points,
        "goals_for_last_5": goals_for,
        "goals_against_last_5": goals_against,
        "avg_goals_for": (
            round(
                goals_for
                / len(finished),
                2,
            )
            if finished
            else None
        ),
        "avg_goals_against": (
            round(
                goals_against
                / len(finished),
                2,
            )
            if finished
            else None
        ),
    }
