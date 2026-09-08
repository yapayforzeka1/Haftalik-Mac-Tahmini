from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any

import requests


# ============================================================
# FOOTBALL-DATA.ORG
# ============================================================

BASE_URL = "https://api.football-data.org/v4"
COMPETITION_CODE = "CL"
REQUEST_TIMEOUT = 30


# ============================================================
# API-FOOTBALL
# ============================================================

API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
API_FOOTBALL_TIMEOUT = 30


class FootballDataError(RuntimeError):
    pass


class FootballDataClient:
    """football-data.org + API-Football veri istemcisi."""

    def __init__(
        self,
        api_key: str | None = None,
    ) -> None:

        # ----------------------------------------------------
        # football-data.org
        # ----------------------------------------------------

        self.api_key = (
            api_key
            or os.environ.get(
                "FOOTBALL_DATA_API_KEY",
                "",
            )
        )

        if not self.api_key:
            raise FootballDataError(
                "FOOTBALL_DATA_API_KEY eksik."
            )

        # ----------------------------------------------------
        # API-Football
        # ----------------------------------------------------

        self.api_football_key = os.environ.get(
            "API_FOOTBALL_KEY",
            "",
        )

        if self.api_football_key:
            print(
                "✅ API_FOOTBALL_KEY bulundu; "
                "ikinci XI kaynağı aktif."
            )
        else:
            print(
                "ℹ️ API_FOOTBALL_KEY bulunamadı; "
                "ikinci XI kaynağı devre dışı."
            )

        # Aynı GitHub Actions çalışması içerisinde
        # API-Football fixture listesini tekrar tekrar
        # çekmemek için basit bir bellek cache'i.
        self._api_football_fixtures_cache: dict[
            str,
            list[dict[str, Any]],
        ] = {}

    # ========================================================
    # FOOTBALL-DATA.ORG
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

        if response.status_code in {401, 403}:

            raise FootballDataError(
                "football-data.org yetki hatası "
                f"({response.status_code})."
            )

        response.raise_for_status()

        return response.json()

    def get_matches(
        self,
    ) -> list[dict[str, Any]]:

        return self._get(
            f"/competitions/{COMPETITION_CODE}/matches"
        ).get(
            "matches",
            [],
        )

    def get_match_details(
        self,
        match_id: int,
    ) -> dict[str, Any]:

        """football-data.org maç detayları + lineup."""

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

        if response.status_code in {401, 403}:

            raise FootballDataError(
                "football-data.org yetki hatası "
                f"({response.status_code})."
            )

        response.raise_for_status()

        return response.json()

    # ========================================================
    # API-FOOTBALL YARDIMCI FONKSİYONLARI
    # ========================================================

    @staticmethod
    def _normalize_team_name(
        name: str,
    ) -> str:

        """
        Takım isimlerini farklı API yazımlarına karşı
        karşılaştırılabilir hale getirir.

        Örnek:
        Real Madrid CF
        Real Madrid
        -> real madrid
        """

        value = str(name or "").lower().strip()

        replacements = {
            "fc": " ",
            "cf": " ",
            "afc": " ",
            "club": " ",
            "football club": " ",
            "calcio": " ",
        }

        for old, new in replacements.items():

            value = re.sub(
                rf"\b{re.escape(old)}\b",
                new,
                value,
            )

        # Türkçe / Avrupa karakterlerini basit şekilde
        # normalize et.
        translation = str.maketrans(
            {
                "ı": "i",
                "İ": "i",
                "ş": "s",
                "Ş": "s",
                "ğ": "g",
                "Ğ": "g",
                "ü": "u",
                "Ü": "u",
                "ö": "o",
                "Ö": "o",
                "ç": "c",
                "Ç": "c",
                "é": "e",
                "è": "e",
                "á": "a",
                "à": "a",
                "ó": "o",
                "ò": "o",
            }
        )

        value = value.translate(
            translation
        )

        value = re.sub(
            r"[^a-z0-9]+",
            " ",
            value,
        )

        return " ".join(
            value.split()
        )

    def _api_football_get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        if not self.api_football_key:

            raise FootballDataError(
                "API_FOOTBALL_KEY eksik."
            )

        response = requests.get(
            f"{API_FOOTBALL_BASE_URL}{path}",
            headers={
                "x-apisports-key": (
                    self.api_football_key
                ),
            },
            params=params or {},
            timeout=API_FOOTBALL_TIMEOUT,
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
                f"API-Football API hatası: "
                f"{errors}"
            )

        return data

    # ========================================================
    # API-FOOTBALL MAÇ BULMA
    # ========================================================

    def _get_api_football_fixtures_for_date(
        self,
        match_date: str,
    ) -> list[dict[str, Any]]:

        """
        Belirli günün API-Football maçlarını getirir.

        Aynı çalışma içerisinde aynı gün için tekrar
        API çağrısı yapılmasını önlemek amacıyla cache kullanır.
        """

        if match_date in (
            self._api_football_fixtures_cache
        ):

            return (
                self._api_football_fixtures_cache[
                    match_date
                ]
            )

        data = self._api_football_get(
            "/fixtures",
            params={
                "date": match_date,
                "timezone": "Europe/Istanbul",
            },
        )

        fixtures = data.get(
            "response",
            [],
        )

        self._api_football_fixtures_cache[
            match_date
        ] = fixtures

        print(
            f"🔎 API-Football: "
            f"{match_date} tarihinde "
            f"{len(fixtures)} fixture bulundu."
        )

        return fixtures

    def find_api_football_fixture(
        self,
        home_team: str,
        away_team: str,
        match_utc: datetime,
    ) -> dict[str, Any] | None:

        """
        football-data.org maçını API-Football karşılığıyla
        takım adı + tarih üzerinden eşleştirir.
        """

        if not self.api_football_key:

            return None

        turkey_date = (
            match_utc.astimezone(
                __import__(
                    "zoneinfo"
                ).ZoneInfo(
                    "Europe/Istanbul"
                )
            ).date().isoformat()
        )

        fixtures = (
            self._get_api_football_fixtures_for_date(
                turkey_date
            )
        )

        target_home = (
            self._normalize_team_name(
                home_team
            )
        )

        target_away = (
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

            api_home = (
                teams.get(
                    "home",
                    {},
                ).get(
                    "name",
                    "",
                )
            )

            api_away = (
                teams.get(
                    "away",
                    {},
                ).get(
                    "name",
                    "",
                )
            )

            normalized_home = (
                self._normalize_team_name(
                    api_home
                )
            )

            normalized_away = (
                self._normalize_team_name(
                    api_away
                )
            )

            score = 0

            if (
                normalized_home
                == target_home
            ):
                score += 2

            if (
                normalized_away
                == target_away
            ):
                score += 2

            # Bir ismin diğerinin içinde geçmesi durumunda
            # daha düşük güven puanı ver.
            if (
                normalized_home
                and target_home
                and (
                    normalized_home
                    in target_home
                    or target_home
                    in normalized_home
                )
            ):
                score += 1

            if (
                normalized_away
                and target_away
                and (
                    normalized_away
                    in target_away
                    or target_away
                    in normalized_away
                )
            ):
                score += 1

            if score > best_score:

                best_score = score
                best_match = fixture

        if (
            best_match is None
            or best_score < 4
        ):

            print(
                f"⚠️ API-Football eşleşmesi bulunamadı: "
                f"{home_team} - {away_team}"
            )

            return None

        fixture_id = (
            best_match.get(
                "fixture",
                {},
            ).get(
                "id"
            )
        )

        print(
            f"✅ API-Football maç eşleşti: "
            f"{home_team} - {away_team} "
            f"(fixture={fixture_id})"
        )

        return best_match

    # ========================================================
    # API-FOOTBALL RESMİ İLK 11
    # ========================================================

    def get_api_football_lineups(
        self,
        home_team: str,
        away_team: str,
        match_utc: datetime,
    ) -> dict[str, Any] | None:

        """
        API-Football'dan resmi ilk 11'i getirir.

        Dönen yapı:
        {
            "status": "ANNOUNCED",
            "home": [...],
            "away": [...],
            "source": "api-football",
            "fixture_id": ...
        }

        XI henüz açıklanmadıysa None döner.
        """

        if not self.api_football_key:

            return None

        try:

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

                print(
                    f"⚠️ API-Football fixture ID yok: "
                    f"{home_team} - {away_team}"
                )

                return None

            data = self._api_football_get(
                "/fixtures/lineups",
                params={
                    "fixture": fixture_id,
                },
            )

            response = data.get(
                "response",
                [],
            )

            if not response:

                print(
                    f"⏳ API-Football: "
                    f"{home_team} - {away_team} "
                    f"için ilk 11 henüz yayınlanmamış."
                )

                return None

            home_lineup: list[
                dict[str, Any]
            ] = []

            away_lineup: list[
                dict[str, Any]
            ] = []

            for team_data in response:

                team = team_data.get(
                    "team",
                    {},
                )

                team_name = self._normalize_team_name(
                    team.get(
                        "name",
                        "",
                    )
                )

                starting = (
                    team_data.get(
                        "startXI",
                        []
                    )
                    or team_data.get(
                        "startingXI",
                        []
                    )
                    or []
                )

                players = []

                for item in starting:

                    player = item.get(
                        "player",
                        {}
                    )

                    if not player:
                        player = item

                    players.append(
                        {
                            "player": player,
                        }
                    )

                if (
                    team_name
                    == self._normalize_team_name(
                        home_team
                    )
                ):

                    home_lineup = players

                elif (
                    team_name
                    == self._normalize_team_name(
                        away_team
                    )
                ):

                    away_lineup = players

            if (
                len(home_lineup) >= 11
                and len(away_lineup) >= 11
            ):

                print(
                    f"✅ API-Football resmi XI "
                    f"doğrulandı: "
                    f"{home_team} - {away_team}"
                )

                return {
                    "status": "ANNOUNCED",
                    "home": home_lineup,
                    "away": away_lineup,
                    "source": "api-football",
                    "fixture_id": fixture_id,
                }

            print(
                f"⏳ API-Football XI eksik: "
                f"{home_team} - {away_team} "
                f"({len(home_lineup)}/11 - "
                f"{len(away_lineup)}/11)"
            )

            return None

        except FootballDataError as error:

            print(
                f"⚠️ API-Football XI hatası: "
                f"{error}"
            )

            return None

        except Exception as error:

            print(
                f"⚠️ API-Football XI beklenmeyen hata: "
                f"{error}"
            )

            return None

    # ========================================================
    # STANDINGS
    # ========================================================

    def get_standings(
        self,
    ) -> list[dict[str, Any]]:

        """
        CL standings football-data.org'da 404 dönebilir.
        Bu durumda standings opsiyonel kabul edilir.
        """

        try:

            return self._get(
                f"/competitions/{COMPETITION_CODE}/standings"
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
                    "⚠️ football-data.org CL standings "
                    "mevcut değil (404). "
                    "Standings atlanacak; analiz devam edecek."
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

        matches = data.get(
            "matches",
            [],
        )

        matches.sort(
            key=lambda item: item.get(
                "utcDate",
                "",
            ),
            reverse=True,
        )

        return matches[:limit]


# ============================================================
# GENEL YARDIMCI FONKSİYONLAR
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
        "last_5": "-".join(
            item["result"]
            for item in finished
        ) or "N/A",
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
