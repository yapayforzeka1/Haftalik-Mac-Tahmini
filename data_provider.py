from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests


BASE_URL = "https://api.football-data.org/v4"
COMPETITION_CODE = "CL"
REQUEST_TIMEOUT = 30


class FootballDataError(RuntimeError):
    pass


class FootballDataClient:
    """Small, rate-limit-conscious wrapper around football-data.org."""

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
            reset = response.headers.get(
                "X-RequestCounter-Reset",
                "bilinmiyor",
            )
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
        data = self._get(
            f"/competitions/{COMPETITION_CODE}/matches"
        )
        return data.get("matches", [])

    def get_standings(self) -> list[dict[str, Any]]:
        """
        Champions League standings endpoint'i bazı durumlarda
        football-data.org tarafından 404 döndürebilir.

        Standings, maç analizinin devam etmesi için zorunlu değildir.
        404 durumunda boş liste döndürülür ve sistem araştırma/AI
        aşamalarına devam eder.

        Diğer HTTP hataları gizlenmez.
        """
        try:
            data = self._get(
                f"/competitions/{COMPETITION_CODE}/standings"
            )
            return data.get("standings", [])

        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)

            if response is not None and response.status_code == 404:
                print(
                    "⚠️ football-data.org CL standings mevcut değil "
                    "(404). Standings atlanacak; analiz devam edecek."
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
        start = (
            before.date() - timedelta(days=days_back)
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

        matches = data.get("matches", [])

        matches.sort(
            key=lambda item: item.get("utcDate", ""),
            reverse=True,
        )

        return matches[:limit]


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


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

        is_home = (
            match.get("homeTeam", {}).get("id")
            == team_id
        )

        gf = home if is_home else away
        ga = away if is_home else home

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
                "date": match.get("utcDate"),
                "competition": match.get(
                    "competition",
                    {},
                ).get("name"),
                "opponent": (
                    match.get("awayTeam", {}).get("name")
                    if is_home
                    else match.get("homeTeam", {}).get("name")
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
                goals_for / len(finished),
                2,
            )
            if finished
            else None
        ),
        "avg_goals_against": (
            round(
                goals_against / len(finished),
                2,
            )
            if finished
            else None
        ),
    }
