ChatGPT:
Tamam. Aşağıdaki iki dosyayı mevcut dosyaların tamamıyla değiştir. Parça ekleme/çıkarma yapma.

Bu sürümde API_FOOTBALL_KEY ikinci kaynak olarak ekleniyor; mevcut FOOTBALL_DATA_API_KEY akışı korunuyor. API-Football'dan fixture bulunup resmi kadrolar çekilmeye çalışılıyor. bot.py de önce football-data.org, sonra API-Football üzerinden XI arıyor.

data_provider.py
from future import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import requests

BASE_URL = "https://api.football-data.org/v4"
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"

COMPETITION_CODE = "CL"
REQUEST_TIMEOUT = 30

class FootballDataError(RuntimeError):
pass

class APIFootballError(RuntimeError):
pass

class FootballDataClient:
"""Rate-limit-conscious wrapper around football-data.org."""

def __init__(self, api_key: str | None = None) -> None:
    self.api_key = api_key or os.environ.get(
        "FOOTBALL_DATA_API_KEY",
        "",
    )

    if not self.api_key:
        raise FootballDataError(
            "FOOTBALL_DATA_API_KEY eksik."
        )

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

def get_matches(self) -> list[dict[str, Any]]:
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

    """Fetch one match with lineup details."""

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

def get_standings(
    self,
) -> list[dict[str, Any]]:

    """CL standings may return 404; standings are optional."""

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

def get_team_matches(
    self,
    team_id: int,
    before: datetime,
    days_back: int = 90,
    limit: int = 20,
) -> list[dict[str, Any]]:

    start = (
        before.date()
        - timedelta(days=days_back)
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

class APIFootballClient:
"""
API-Football ikinci veri kaynağı.

Kullanım:
- Fixture arama
- Fixture lineup çekme
- Resmi ilk 11 kontrolü

Secret:
    API_FOOTBALL_KEY
"""

def __init__(
    self,
    api_key: str | None = None,
) -> None:

    self.api_key = api_key or os.environ.get(
        "API_FOOTBALL_KEY",
        "",
    )

    if not self.api_key:
        raise APIFootballError(
            "API_FOOTBALL_KEY eksik."
        )

def _get(
    self,
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:

    response = requests.get(
        f"{API_FOOTBALL_BASE_URL}{path}",
        headers={
            "x-apisports-key": self.api_key,
        },
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code == 429:
        raise APIFootballError(
            "API-Football rate limit (429)."
        )

    if response.status_code in {401, 403}:
        raise APIFootballError(
            "API-Football yetki hatası "
            f"({response.status_code})."
        )

    response.raise_for_status()

    data = response.json()

    errors = data.get("errors")

    if errors:

        if isinstance(errors, dict):

            error_text = "; ".join(
                f"{key}: {value}"
                for key, value in errors.items()
            )

        else:

            error_text = str(errors)

        raise APIFootballError(
            f"API-Football API hatası: {error_text}"
        )

    return data

@staticmethod
def _normalise_name(
    value: str,
) -> str:

    replacements = {
        "fc": "",
        "cf": "",
        "afc": "",
        "sk": "",
        "ac": "",
        "rc": "",
        "real": "real",
    }

    value = (
        value.lower()
        .replace(".", " ")
        .replace("-", " ")
        .replace("_", " ")
    )

    parts = []

    for part in value.split():

        if part in replacements:
            replacement = replacements[part]

            if replacement:
                parts.append(replacement)

        else:
            parts.append(part)

    return " ".join(parts).strip()

@classmethod
def _team_names_match(
    cls,
    left: str,
    right: str,
) -> bool:

    a = cls._normalise_name(left)
    b = cls._normalise_name(right)

    if a == b:
        return True

    a_tokens = set(a.split())
    b_tokens = set(b.split())

    if not a_tokens or not b_tokens:
        return False

    intersection = a_tokens & b_tokens

    return (
        len(intersection) >= 2
        or a in b
        or b in a
    )

def find_fixture(
    self,
    home_team: str,
    away_team: str,
    kickoff_utc: datetime,
) -> dict[str, Any] | None:

    """
    API-Football fixture arar.

    Önce tarih bazlı fixture listesi alınır.
    Ardından ev/deplasman takım isimleri eşleştirilir.
    """

    date_value = kickoff_utc.date().isoformat()

    data = self._get(
        "/fixtures",
        params={
            "date": date_value,
        },
    )

    fixtures = data.get(
        "response",
        [],
    )

    best_match = None
    best_score = -1

    for fixture in fixtures:

        fixture_teams = fixture.get(
            "teams",
            {},
        )

        fixture_home = (
            fixture_teams.get(
                "home",
                {},
            ).get(
                "name",
                "",
            )
        )

        fixture_away = (
            fixture_teams.get(
                "away",
                {},
            ).get(
                "name",
                "",
            )
        )

        if not fixture_home or not fixture_away:
            continue

        home_match = self._team_names_match(
            home_team,
            fixture_home,
        )

        away_match = self._team_names_match(
            away_team,
            fixture_away,
        )

        if not home_match or not away_match:
            continue

        fixture_date = (
            fixture.get(
                "fixture",
                {},
            ).get(
                "date"
            )
        )

        score = 0

        if fixture_date:
            try:

                fixture_dt = datetime.fromisoformat(
                    fixture_date.replace(
                        "Z",
                        "+00:00",
                    )
                )

                diff_minutes = abs(
                    (
                        fixture_dt
                        - kickoff_utc
                    ).total_seconds()
                    / 60
                )

                if diff_minutes <= 30:
                    score += 10

                elif diff_minutes <= 120:
                    score += 5

            except ValueError:
                pass

        if home_match:
            score += 10

        if away_match:
            score += 10

        if score > best_score:

            best_score = score
            best_match = fixture

    return best_match

def get_fixture_lineups(
    self,
    fixture_id: int,
) -> dict[str, Any]:

    data = self._get(
        "/fixtures/lineups",
        params={
            "fixture": fixture_id,
        },
    )

    return {
        "response": data.get(
            "response",
            [],
        ),
    }

def get_match_official_xi(
    self,
    home_team: str,
    away_team: str,
    kickoff_utc: datetime,
) -> dict[str, Any] | None:

    fixture = self.find_fixture(
        home_team,
        away_team,
        kickoff_utc,
    )

    if not fixture:
        print(
            f"⚠️ API-Football fixture bulunamadı: "
            f"{home_team} - {away_team}"
        )

        return None

    fixture_data = fixture.get(
        "fixture",
        {},
    )

    fixture_id = fixture_data.get(
        "id"
    )

    if fixture_id is None:
        return None

    lineups_data = self.get_fixture_lineups(
        int(fixture_id)
    )

    lineups = lineups_data.get(
        "response",
        [],
    )

    home_lineup = None
    away_lineup = None

    for lineup in lineups:

        team_name = (
            lineup.get(
                "team",
                {},
            ).get(
                "name",
                "",
            )
        )

        if self._team_names_match(
            home_team,
            team_name,
        ):

            home_lineup = lineup

        elif self._team_names_match(
            away_team,
            team_name,
        ):

            away_lineup = lineup

    if not home_lineup or not away_lineup:
        return None

    home_players = (
        home_lineup.get(
            "startXI",
            [],
        )
    )

    away_players = (
        away_lineup.get(
            "startXI",
            [],
        )
    )

    if not home_players or not away_players:
        return None

    home_xi = [
        item.get(
            "player",
            {},
        )
        for item in home_players
        if item.get(
            "player"
        )
    ]

    away_xi = [
        item.get(
            "player",
            {},
        )
        for item in away_players
        if item.get(
            "player"
        )
    ]

    if (
        len(home_xi) < 11
        or len(away_xi) < 11
    ):
        return None

    return {
        "status": "ANNOUNCED",
        "home": home_xi,
        "away": away_xi,
        "source": "API-Football",
        "fixture_id": fixture_id,
    }

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

    home = score.get("home")
    away = score.get("away")

    if home is None or away is None:
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
            "date": match.get(
                "utcDate"
            ),
            "competition": match.get(
                "competition",
                {},
            ).get(
                "name"
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

bot.py
Senin gönderdiğin bot.pynin geri kalanını değiştirmiyoruz; tam dosyayı aşağıdaki sürümle değiştir:

from future import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

from ai_pool import run_ai_pool
from consensus_engine import build_consensus
from data_provider import (
FootballDataClient,
FootballDataError,
APIFootballClient,
APIFootballError,
build_team_form,
parse_utc,
)
from history_engine import (
build_ai_performance,
build_team_history,
grade_record,
)
from report_engine import (
build_result_message,
build_telegram_group_message,
)
from research_engine import (
empty_research,
research_match,
)
from v2_context import enrich_team_context
from match_report import (
kickoff_key,
render_match_group_image,
)
from weekly_report import (
build_general_snapshot,
build_weekly_snapshot,
load_weekly_reports,
MODEL_ORDER,
render_general_image,
render_weekly_image,
save_weekly_reports,
)

TURKEY_TZ = ZoneInfo("Europe/Istanbul")

MIN_MINUTES_BEFORE = 15
MAX_MINUTES_BEFORE = 75

MATCH_DISCOVERY_MAX_MINUTES = 180

LINEUP_REQUIRED = True

MATCHES_FILE = Path("match_predictions.json")
WEEKLY_SCHEDULE_FILE = Path("weekly_schedule.json")

SEASON = "2026/27"

TERMINAL_STATUSES = {
"POSTPONED",
"CANCELLED",
"SUSPENDED",
"ABANDONED",
}

def load_predictions() -> dict[str, Any]:

if not MATCHES_FILE.exists():
    return {}

try:

    return json.loads(
        MATCHES_FILE.read_text(
            encoding="utf-8"
        )
    )

except Exception as error:

    print(
        f"⚠️ {MATCHES_FILE} okunamadı: {error}"
    )

    return {}

def save_predictions(
predictions: dict[str, Any],
) -> None:

temp = MATCHES_FILE.with_suffix(".tmp")

temp.write_text(
    json.dumps(
        predictions,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

temp.replace(MATCHES_FILE)

def send_telegram_message(
message: str,
) -> None:

import requests

response = requests.post(
    (
        "https://api.telegram.org/"
        f"bot{os.environ['TELEGRAM_BOT_TOKEN']}"
        "/sendMessage"
    ),
    data={
        "chat_id": os.environ[
            "TELEGRAM_CHAT_ID"
        ],
        "text": message,
    },
    timeout=30,
)

response.raise_for_status()

def send_telegram_photo(
path: Path,
caption: str | None = None,
) -> None:

import requests

with path.open("rb") as photo:

    data = {
        "chat_id": os.environ[
            "TELEGRAM_CHAT_ID"
        ],
    }

    if caption:
        data["caption"] = caption

    response = requests.post(
        (
            "https://api.telegram.org/"
            f"bot{os.environ['TELEGRAM_BOT_TOKEN']}"
            "/sendPhoto"
        ),
        data=data,
        files={
            "photo": photo
        },
        timeout=60,
    )

response.raise_for_status()

def send_analysis_telegram_photo(
path: Path,
caption: str | None = None,
) -> None:

import requests

token = os.environ.get(
    "ANALYSIS_TELEGRAM_BOT_TOKEN"
)

chat_id = os.environ.get(
    "ANALYSIS_TELEGRAM_CHAT_ID"
)

if not token or not chat_id:

    raise RuntimeError(
        "Bot 2 secretleri eksik: "
        "ANALYSIS_TELEGRAM_BOT_TOKEN / "
        "ANALYSIS_TELEGRAM_CHAT_ID"
    )

with path.open("rb") as photo:

    data = {
        "chat_id": chat_id,
    }

    if caption:
        data["caption"] = caption

    response = requests.post(
        (
            "https://api.telegram.org/"
            f"bot{token}"
            "/sendPhoto"
        ),
        data=data,
        files={
            "photo": photo
        },
        timeout=60,
    )

response.raise_for_status()

def build_standings_map(
standings: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:

result: dict[
    int,
    dict[str, Any]
] = {}

for group in standings:

    if group.get("type") != "TOTAL":
        continue

    for row in group.get(
        "table",
        [],
    ):

        team = row.get(
            "team",
            {}
        )

        if team.get("id") is not None:

            result[
                int(team["id"])
            ] = {
                "position": row.get(
                    "position"
                ),
                "played": row.get(
                    "playedGames"
                ),
                "points": row.get(
                    "points"
                ),
                "goals_for": row.get(
                    "goalsFor"
                ),
                "goals_against": row.get(
                    "goalsAgainst"
                ),
            }

return result

def update_finished_results(
predictions: dict[str, Any],
matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:

changed = []

by_id = {
    str(m.get("id")): m
    for m in matches
}

for match_id, record in predictions.items():

    if record.get("actual"):
        continue

    match = by_id.get(
        str(match_id)
    )

    if (
        not match
        or match.get("status")
        != "FINISHED"
    ):
        continue

    score = (
        match.get("score", {})
        .get("fullTime", {})
    )

    if (
        score.get("home") is None
        or score.get("away") is None
    ):
        continue

    record["actual"] = {
        "home": score["home"],
        "away": score["away"],
        "status": "FINISHED",
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    grade_record(record)

    changed.append(record)

return changed

def _upcoming_matches(
matches: list[dict[str, Any]],
now_utc: datetime,
test_mode: bool,
) -> list[
tuple[
dict[str, Any],
float
]
]:

candidates = []

for match in matches:

    if match.get("status") not in {
        "SCHEDULED",
        "TIMED",
    }:
        continue

    try:

        match_utc = parse_utc(
            match["utcDate"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):

        continue

    minutes_until = (
        (
            match_utc
            - now_utc
        ).total_seconds()
        / 60
    )

    if test_mode:

        if minutes_until > 0:

            candidates.append(
                (
                    match,
                    minutes_until,
                )
            )

    else:

        if (
            0
            <= minutes_until
            <= MATCH_DISCOVERY_MAX_MINUTES
        ):

            candidates.append(
                (
                    match,
                    minutes_until,
                )
            )

if test_mode and candidates:

    candidates.sort(
        key=lambda item: item[1]
    )

    nearest_key = parse_utc(
        candidates[0][0]["utcDate"]
    ).strftime(
        "%Y-%m-%dT%H:%M"
    )

    return [
        item
        for item in candidates
        if parse_utc(
            item[0]["utcDate"]
        ).strftime(
            "%Y-%m-%dT%H:%M"
        )
        == nearest_key
    ]

return candidates

def _print_prediction_window_debug(
matches: list[dict[str, Any]],
now_utc: datetime,
) -> None:

debug_candidates: list[
    tuple[
        float,
        dict[str, Any],
        datetime,
    ]
] = []

for match in matches:

    if match.get("status") not in {
        "SCHEDULED",
        "TIMED",
    }:
        continue

    try:

        match_utc = parse_utc(
            match["utcDate"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):

        continue

    minutes_until = (
        (
            match_utc
            - now_utc
        ).total_seconds()
        / 60
    )

    if (
        -180
        <= minutes_until
        <= 180
    ):

        debug_candidates.append(
            (
                minutes_until,
                match,
                match_utc,
            )
        )

debug_candidates.sort(
    key=lambda item: abs(item[0])
)

print("")
print("=" * 80)
print("🔎 TAHMİN PENCERESİ TEŞHİSİ")
print("=" * 80)

print(
    f"🕐 Şu an UTC      : "
    f"{now_utc.isoformat()}"
)

print(
    f"🇹🇷 Şu an Türkiye : "
    f"{now_utc.astimezone(TURKEY_TZ).strftime('%d.%m.%Y %H:%M:%S %Z')}"
)

print(
    f"🎯 Aranan pencere : "
    f"{MIN_MINUTES_BEFORE}-"
    f"{MAX_MINUTES_BEFORE} dakika"
)

print(
    f"🔎 Keşif penceresi : "
    f"0-{MATCH_DISCOVERY_MAX_MINUTES} dakika"
)

print(
    "📊 Uygun durumlar : "
    "SCHEDULED / TIMED"
)

if not debug_candidates:

    print(
        "❌ Şu an ±180 dakika içerisinde "
        "SCHEDULED/TIMED maç bulunamadı."
    )

else:

    print(
        f"📋 Yakındaki maç sayısı: "
        f"{len(debug_candidates)}"
    )

    for index, (
        minutes_until,
        match,
        match_utc,
    ) in enumerate(
        debug_candidates[:15],
        start=1,
    ):

        home = (
            match.get(
                "homeTeam",
                {},
            ).get(
                "name",
                "?",
            )
        )

        away = (
            match.get(
                "awayTeam",
                {},
            ).get(
                "name",
                "?",
            )
        )

        turkey_time = (
            match_utc.astimezone(
                TURKEY_TZ
            )
        )

        print(
            f"{index:02d}. "
            f"{home} - {away} | "
            f"API UTC: {match.get('utcDate')} | "
            f"Türkiye: "
            f"{turkey_time.strftime('%d.%m.%Y %H:%M:%S')} | "
            f"Kalan: "
            f"{minutes_until:+.1f} dk | "
            f"Status: "
            f"{match.get('status')}"
        )

print("=" * 80)
print("🔎 TEŞHİS SONU")
print("")

def _load_weekly_schedule() -> dict[str, str]:

if not WEEKLY_SCHEDULE_FILE.exists():
    return {}

try:

    return json.loads(
        WEEKLY_SCHEDULE_FILE.read_text(
            encoding="utf-8"
        )
    )

except Exception as error:

    print(
        f"⚠️ {WEEKLY_SCHEDULE_FILE} "
        f"okunamadı: {error}"
    )

    return {}

def _save_weekly_schedule(
data: dict[str, str],
) -> None:

temp = (
    WEEKLY_SCHEDULE_FILE
    .with_suffix(".tmp")
)

temp.write_text(
    json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

temp.replace(
    WEEKLY_SCHEDULE_FILE
)

def _planned_last_kickoff_by_matchday(
matches: list[dict[str, Any]],
) -> dict[int, datetime]:

schedule = _load_weekly_schedule()

result: dict[
    int,
    datetime
] = {}

changed = False

for match in matches:

    md = match.get(
        "matchday"
    )

    if md is None:
        continue

    try:

        matchday = int(md)

        kickoff = parse_utc(
            match["utcDate"]
        )

    except (
        ValueError,
        TypeError,
        KeyError,
    ):

        continue

    key = str(matchday)

    if key in schedule:

        try:

            result[
                matchday
            ] = datetime.fromisoformat(
                schedule[key].replace(
                    "Z",
                    "+00:00",
                )
            )

            continue

        except ValueError:
            pass

    if match.get(
        "status"
    ) in TERMINAL_STATUSES:

        continue

    if (
        matchday not in result
        or kickoff > result[
            matchday
        ]
    ):

        result[
            matchday
        ] = kickoff

for matchday, kickoff in result.items():

    key = str(matchday)

    if key not in schedule:

        schedule[key] = (
            kickoff.isoformat()
        )

        changed = True

if changed:

    _save_weekly_schedule(
        schedule
    )

return result

def _build_report_test_data() -> tuple[
dict[str, Any],
dict[str, Any],
]:

def record(
    match_id: str,
    matchday: int,
    home: str,
    away: str,
    actual_h: int,
    actual_a: int,
    scores: list[str],
    consensus_score: str,
    kickoff: str,
) -> dict[str, Any]:

    votes = []

    actual_outcome = (
        "HOME"
        if actual_h > actual_a
        else "AWAY"
        if actual_h < actual_a
        else "DRAW"
    )

    for model, score in zip(
        MODEL_ORDER,
        scores,
    ):

        ph, pa = (
            int(x)
            for x in score.split("-")
        )

        pred_outcome = (
            "HOME"
            if ph > pa
            else "AWAY"
            if ph < pa
            else "DRAW"
        )

        exact = (
            score
            == f"{actual_h}-{actual_a}"
        )

        outcome_correct = (
            pred_outcome
            == actual_outcome
        )

        points = (
            5
            if exact
            or (
                pred_outcome == "DRAW"
                and actual_outcome == "DRAW"
            )
            else 3
            if outcome_correct
            else 0
        )

        votes.append({
            "model": model,
            "success": True,
            "result": {
                "score": score,
                "outcome": pred_outcome,
            },
            "points": points,
            "exact_score_correct": exact,
            "outcome_correct": outcome_correct,
        })

    ch, ca = (
        int(x)
        for x in consensus_score.split("-")
    )

    c_outcome = (
        "HOME"
        if ch > ca
        else "AWAY"
        if ch < ca
        else "DRAW"
    )

    c_exact = (
        consensus_score
        == f"{actual_h}-{actual_a}"
    )

    c_outcome_correct = (
        c_outcome
        == actual_outcome
    )

    c_points = (
        5
        if c_exact
        or (
            c_outcome == "DRAW"
            and actual_outcome == "DRAW"
        )
        else 3
        if c_outcome_correct
        else 0
    )

    return {
        "season": SEASON,
        "matchday": matchday,
        "match_id": match_id,
        "home_team": home,
        "away_team": away,
        "match_time": kickoff,
        "match_utc": datetime.strptime(
            kickoff,
            "%d.%m.%Y %H:%M",
        ).replace(
            tzinfo=TURKEY_TZ
        ).astimezone(
            timezone.utc
        ).isoformat(),
        "actual": {
            "home": actual_h,
            "away": actual_a,
        },
        "ai_votes": votes,
        "consensus": {
            "score": consensus_score,
            "outcome": c_outcome,
        },
        "consensus_points": c_points,
        "exact_score_correct": c_exact,
        "outcome_correct": c_outcome_correct,
    }

md1 = [
    record(
        "test-101",
        1,
        "Juventus",
        "Borussia Dortmund",
        4,
        1,
        ["3-1", "2-1", "4-1", "3-1", "4-2"],
        "3-1",
        "08.09.2026 19:45",
    ),
    record(
        "test-102",
        1,
        "Real Madrid",
        "Marseille",
        2,
        1,
        ["2-0", "3-1", "2-1", "1-1", "2-1"],
        "2-1",
        "08.09.2026 19:45",
    ),
    record(
        "test-103",
        1,
        "Benfica",
        "Qarabag",
        2,
        0,
        ["2-0", "1-0", "2-0", "2-1", "2-0"],
        "2-0",
        "08.09.2026 22:00",
    ),
    record(
        "test-104",
        1,
        "Tottenham",
        "Villarreal",
        1,
        1,
        ["1-1", "2-1", "1-1", "1-1", "0-1"],
        "1-1",
        "08.09.2026 22:00",
    ),
    record(
        "test-105",
        1,
        "Olympiacos",
        "Pafos",
        2,
        1,
        ["1-1", "2-1", "2-0", "2-1", "1-0"],
        "2-1",
        "08.09.2026 22:00",
    ),
    record(
        "test-106",
        1,
        "Ajax",
        "Inter",
        0,
        2,
        ["0-2", "1-2", "0-2", "0-2", "0-2"],
        "0-2",
        "08.09.2026 22:00",
    ),
    record(
        "test-107",
        1,
        "Slavia Prag",
        "Bodo/Glimt",
        2,
        2,
        ["1-1", "2-2", "1-2", "2-1", "1-1"],
        "1-1",
        "08.09.2026 22:00",
    ),
    record(
        "test-108",
        1,
        "Bayern Munih",
        "Chelsea",
        3,
        1,
        ["2-1", "3-1", "3-0", "3-1", "2-1"],
        "3-1",
        "08.09.2026 22:00",
    ),
    record(
        "test-109",
        1,
        "Liverpool",
        "Atletico Madrid",
        3,
        2,
        ["2-1", "3-2", "2-2", "3-1", "2-2"],
        "2-2",
        "08.09.2026 22:00",
    ),
]

md2 = [
    record(
        "test-201",
        2,
        "Liverpool",
        "Milan",
        2,
        1,
        ["2-1", "1-1", "2-0", "2-1", "3-1"],
        "2-1",
        "13.10.2026 19:45",
    ),
    record(
        "test-202",
        2,
        "Barcelona",
        "Dortmund",
        1,
        2,
        ["1-0", "1-2", "2-1", "1-2", "0-1"],
        "1-2",
        "13.10.2026 22:00",
    ),
    record(
        "test-203",
        2,
        "City",
        "Napoli",
        2,
        2,
        ["2-1", "1-1", "2-2", "3-2", "0-0"],
        "2-2",
        "13.10.2026 22:00",
    ),
    record(
        "test-204",
        2,
        "PSG",
        "Benfica",
        3,
        0,
        ["3-0", "2-0", "3-1", "3-0", "2-0"],
        "3-0",
        "13.10.2026 22:00",
    ),
]

predictions = {
    r["match_id"]: r
    for r in md1 + md2
}

planned = [
    {
        "id": r["match_id"],
        "matchday": r["matchday"],
        "status": "FINISHED",
        "homeTeam": {
            "name": r["home_team"]
        },
        "awayTeam": {
            "name": r["away_team"]
        },
    }
    for r in md1 + md2
]

reports = {
    "1": build_weekly_snapshot(
        predictions,
        1,
        planned,
    ),
    "2": build_weekly_snapshot(
        predictions,
        2,
        planned,
    ),
}

return predictions, reports

def run_weekly_report_test() -> None:

predictions, reports = (
    _build_report_test_data()
)

weekly_image = render_weekly_image(
    reports["2"],
    predictions,
)

general_image = render_general_image(
    reports
)

send_analysis_telegram_photo(
    weekly_image,
    "🧪 TEST • Matchday 2 — Haftalık Performans",
)

send_analysis_telegram_photo(
    general_image,
    "🧪 TEST • Genel Performans",
)

print(
    "✅ Haftalık + genel performans "
    "görselleri TEST olarak Telegram'a gönderildi."
)

def maybe_send_weekly_reports(
predictions: dict[str, Any],
matches: list[dict[str, Any]],
now_utc: datetime,
) -> bool:

weekly_reports = (
    load_weekly_reports()
)

last_kickoffs = (
    _planned_last_kickoff_by_matchday(
        matches
    )
)

changed = False

for matchday, last_kickoff in sorted(
    last_kickoffs.items()
):

    if now_utc < (
        last_kickoff
        + timedelta(hours=1)
    ):
        continue

    key = str(matchday)

    if key in weekly_reports:
        continue

    snapshot = (
        weekly_reports.get(key)
        or build_weekly_snapshot(
            predictions,
            matchday,
            matches,
        )
    )

    snapshot.setdefault(
        "last_planned_kickoff",
        last_kickoffs[
            matchday
        ].isoformat(),
    )

    weekly_reports[key] = snapshot

    changed = True

    if not snapshot.get(
        "telegram_sent"
    ):

        weekly_image = (
            render_weekly_image(
                snapshot,
                predictions,
            )
        )

        general_image = (
            render_general_image(
                weekly_reports
            )
        )

        try:

            if not snapshot.get(
                "weekly_photo_sent"
            ):

                send_analysis_telegram_photo(
                    weekly_image,
                    (
                        f"🏆 Matchday {matchday} "
                        f"— Haftalık Performans"
                    ),
                )

                snapshot[
                    "weekly_photo_sent"
                ] = True

                save_weekly_reports(
                    weekly_reports
                )

            if not snapshot.get(
                "general_photo_sent"
            ):

                send_analysis_telegram_photo(
                    general_image,
                    "🏆 Genel Performans",
                )

                snapshot[
                    "general_photo_sent"
                ] = True

                save_weekly_reports(
                    weekly_reports
                )

            snapshot[
                "telegram_sent"
            ] = True

            save_weekly_reports(
                weekly_reports
            )

            print(
                f"✅ Matchday {matchday} "
                f"haftalık + genel performans "
                f"raporları Telegram'a gönderildi."
            )

        except Exception as error:

            save_weekly_reports(
                weekly_reports
            )

            print(
                f"⚠️ Haftalık rapor "
                f"Telegram hatası: {error}"
            )

    else:

        save_weekly_reports(
            weekly_reports
        )

return changed

def _get_official_xi(
football: FootballDataClient,
api_football: APIFootballClient | None,
match: dict[str, Any],
match_utc: datetime,
home_team: str,
away_team: str,
) -> dict[str, Any] | None:

"""
Resmi XI için iki aşamalı doğrulama:

1. football-data.org
2. API-Football

İlk kaynakta XI yoksa ikinci kaynak denenir.
"""

# ========================================================
# KAYNAK 1 — football-data.org
# ========================================================

try:

    details = football.get_match_details(
        int(match["id"])
    )

    lineups = (
        details.get(
            "lineups"
        )
        or {}
    )

    home_xi = (
        lineups.get(
            "homeTeam"
        )
        or {}
    ).get(
        "lineup"
    ) or []

    away_xi = (
        lineups.get(
            "awayTeam"
        )
        or {}
    ).get(
        "lineup"
    ) or []

    if (
        len(home_xi) >= 11
        and len(away_xi) >= 11
    ):

        print(
            f"✅ {home_team} - {away_team}: "
            f"resmi ilk 11 football-data.org "
            f"üzerinden doğrulandı."
        )

        return {
            "status": "ANNOUNCED",
            "home": home_xi,
            "away": away_xi,
            "source": (
                "football-data.org "
                "match lineup"
            ),
        }

    print(
        f"⏳ {home_team} - {away_team}: "
        f"football-data.org XI henüz tam değil "
        f"({len(home_xi)}/11 - "
        f"{len(away_xi)}/11)."
    )

except FootballDataError as error:

    print(
        f"⚠️ football-data.org XI alınamadı: "
        f"{error}"
    )

# ========================================================
# KAYNAK 2 — API-Football
# ========================================================

if api_football is None:

    print(
        f"⚠️ {home_team} - {away_team}: "
        f"API_FOOTBALL_KEY bulunmadığı için "
        f"ikinci XI kaynağı kullanılamıyor."
    )

    return None

try:

    api_xi = (
        api_football.get_match_official_xi(
            home_team,
            away_team,
            match_utc,
        )
    )

    if api_xi:

        print(
            f"✅ {home_team} - {away_team}: "
            f"resmi ilk 11 API-Football "
            f"üzerinden doğrulandı."
        )

        return api_xi

    print(
        f"⏳ {home_team} - {away_team}: "
        f"API-Football da henüz tam XI vermiyor."
    )

except APIFootballError as error:

    print(
        f"⚠️ API-Football XI alınamadı: "
        f"{error}"
    )

except Exception as error:

    print(
        f"⚠️ API-Football beklenmeyen XI hatası: "
        f"{error}"
    )

return None

def main() -> None:

required = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "FOOTBALL_DATA_API_KEY",
]

missing = [
    x
    for x in required
    if not os.environ.get(x)
]

if missing:

    raise RuntimeError(
        f"Eksik secret: "
        f"{', '.join(missing)}"
    )

report_test_mode = (
    os.environ.get(
        "REPORT_TEST_MODE",
        "false",
    ).lower()
    == "true"
)

if report_test_mode:

    print(
        "🧪 HAFTALIK RAPOR TEST MODU AKTİF — "
        "BOT 2 RAPORLARI GÖNDERİLECEK"
    )

    run_weekly_report_test()

    print(
        "➡️ Bot 2 test raporu tamamlandı; "
        "Bot 1 normal/test akışına devam ediyor."
    )

predictions = (
    load_predictions()
)

football = FootballDataClient()

api_football = None

if os.environ.get(
    "API_FOOTBALL_KEY"
):

    try:

        api_football = APIFootballClient()

        print(
            "✅ API-Football ikinci veri kaynağı aktif."
        )

    except APIFootballError as error:

        print(
            f"⚠️ API-Football başlatılamadı: "
            f"{error}"
        )

else:

    print(
        "⚠️ API_FOOTBALL_KEY bulunamadı. "
        "Sadece football-data.org kullanılacak."
    )

matches = (
    football.get_matches()
)

now_utc = datetime.now(
    timezone.utc
)

finished_updates = (
    update_finished_results(
        predictions,
        matches,
    )
)

for record in finished_updates:

    if not record.get(
        "result_sent"
    ):

        try:

            send_telegram_message(
                build_result_message(
                    record
                )
            )

            record[
                "result_sent"
            ] = True

        except Exception as error:

            print(
                f"⚠️ Sonuç Telegram hatası: "
                f"{error}"
            )

if finished_updates:

    save_predictions(
        predictions
    )

try:

    maybe_send_weekly_reports(
        predictions,
        matches,
        now_utc,
    )

except Exception as error:

    print(
        f"⚠️ Haftalık rapor oluşturma hatası: "
        f"{error}"
    )

test_mode = (
    os.environ.get(
        "TEST_MODE",
        "false",
    ).lower()
    == "true"
)

if test_mode:

    print(
        "🧪 TEST MODU AKTİF"
    )

    print(
        "TEST MODU: resmi XI bekleme "
        "kuralı bypass edilir; "
        "en yakın gelecek maç kullanılabilir."
    )

upcoming = (
    _upcoming_matches(
        matches,
        now_utc,
        test_mode,
    )
)

print(
    f"Toplam {len(matches)} maç; "
    f"{'TEST MODUNDA' if test_mode else 'keşif penceresinde'} "
    f"{len(upcoming)} maç bulundu."
)

if not upcoming:

    if not test_mode:

        _print_prediction_window_debug(
            matches,
            now_utc,
        )

    save_predictions(
        predictions
    )

    return

prediction_candidates = []

for match, minutes_until in upcoming:

    if test_mode:

        prediction_candidates.append(
            (
                match,
                minutes_until,
            )
        )

        continue

    if (
        MIN_MINUTES_BEFORE
        <= minutes_until
        <= MAX_MINUTES_BEFORE
    ):

        prediction_candidates.append(
            (
                match,
                minutes_until,
            )
        )

    else:

        print(
            f"⏳ {match.get('homeTeam', {}).get('name', '?')} - "
            f"{match.get('awayTeam', {}).get('name', '?')}: "
            f"{minutes_until:.1f} dk kaldı; "
            f"tahmin penceresi "
            f"{MIN_MINUTES_BEFORE}-"
            f"{MAX_MINUTES_BEFORE} dk."
        )

print(
    f"🎯 Tahmin penceresinde "
    f"{len(prediction_candidates)} maç var."
)

if not prediction_candidates:

    save_predictions(
        predictions
    )

    return

try:

    standings_map = (
        build_standings_map(
            football.get_standings()
        )
    )

except FootballDataError as error:

    print(
        f"⚠️ Puan durumu alınamadı: "
        f"{error}"
    )

    standings_map = {}

research_client = None

if os.environ.get(
    "GEMINI_API_KEY"
):

    from google import genai

    research_client = genai.Client(
        api_key=os.environ[
            "GEMINI_API_KEY"
        ]
    )

prepared_records: list[
    dict[str, Any]
] = []

for match, minutes_until in (
    prediction_candidates
):

    match_id = str(
        match["id"]
    )

    home_team = (
        match["homeTeam"]["name"]
    )

    away_team = (
        match["awayTeam"]["name"]
    )

    if (
        not test_mode
        and predictions.get(
            match_id,
            {},
        ).get("final_sent")
    ):

        print(
            f"⏭️ {home_team} - {away_team}: "
            f"zaten gönderildi."
        )

        continue

    match_utc = parse_utc(
        match["utcDate"]
    )

    context = {
        "season": SEASON,
        "matchday": match.get(
            "matchday"
        ),
        "stage": match.get(
            "stage"
        ),
        "venue": match.get(
            "venue"
        ),
        "home": {
            "team_id": int(
                match[
                    "homeTeam"
                ]["id"]
            ),
            "standings": standings_map.get(
                int(
                    match[
                        "homeTeam"
                    ]["id"]
                )
            ),
        },
        "away": {
            "team_id": int(
                match[
                    "awayTeam"
                ]["id"]
            ),
            "standings": standings_map.get(
                int(
                    match[
                        "awayTeam"
                    ]["id"]
                )
            ),
        },
    }

    try:

        home_matches = (
            football.get_team_matches(
                context[
                    "home"
                ]["team_id"],
                match_utc,
            )
        )

        away_matches = (
            football.get_team_matches(
                context[
                    "away"
                ]["team_id"],
                match_utc,
            )
        )

        context[
            "home"
        ]["last_5"] = (
            enrich_team_context(
                build_team_form(
                    home_matches,
                    context[
                        "home"
                    ]["team_id"],
                ),
                match_utc,
            )
        )

        context[
            "away"
        ]["last_5"] = (
            enrich_team_context(
                build_team_form(
                    away_matches,
                    context[
                        "away"
                    ]["team_id"],
                ),
                match_utc,
            )
        )

    except FootballDataError as error:

        context[
            "data_warning"
        ] = str(error)

        print(
            f"⚠️ Son maç verileri alınamadı: "
            f"{error}"
        )

    # ====================================================
    # RESMİ İLK 11 — İKİ KAYNAK
    # ====================================================

    official_xi_context = _get_official_xi(
        football,
        api_football,
        match,
        match_utc,
        home_team,
        away_team,
    )

    if official_xi_context:

        context[
            "official_xi"
        ] = official_xi_context

    history = {
        "home": build_team_history(
            predictions,
            home_team,
        ),
        "away": build_team_history(
            predictions,
            away_team,
        ),
        "ai_performance": (
            build_ai_performance(
                predictions
            )
        ),
    }

    # ====================================================
    # ARAŞTIRMA
    # ====================================================

    if research_client:

        try:

            research = research_match(
                research_client,
                home_team,
                away_team,
                {
                    "context": context,
                    "history": history,
                },
            )

        except Exception as error:

            print(
                f"⚠️ Araştırma başarısız; "
                f"AI yapılandırılmış verilerle "
                f"devam edecek: {error}"
            )

            research = empty_research(
                str(error)
            )

    else:

        print(
            "ℹ️ GEMINI_API_KEY yok; "
            "araştırma katmanı atlandı."
        )

        research = empty_research(
            "GEMINI_API_KEY yok; "
            "araştırma katmanı atlandı."
        )

    # ====================================================
    # RESEARCH KATMANINDAN XI KONTROLÜ
    # ====================================================

    research_xi = (
        research.get(
            "official_xi"
        )
        or {}
    ) if isinstance(
        research,
        dict,
    ) else {}

    research_xi_announced = (
        research_xi.get(
            "status"
        )
        == "ANNOUNCED"
    )

    # ====================================================
    # XI YOKSA TAHMİN GÖNDERME
    # ====================================================

    if (
        not test_mode
        and not (
            official_xi_context
            or research_xi_announced
        )
    ):

        print(
            f"⏳ {home_team} - {away_team}: "
            f"resmi ilk 11 iki veri kaynağında "
            f"da doğrulanmadı; tahmin ertelendi."
        )

        continue

    # ====================================================
    # AI POOL
    # ====================================================

    votes = run_ai_pool(
        home_team,
        away_team,
        context,
        research,
        history,
    )

    successful = [
        v
        for v in votes
        if v.success
        and v.result
    ]

    if len(successful) < 3:

        print(
            f"⚠️ {home_team} - {away_team}: "
            f"yalnızca "
            f"{len(successful)}/5 AI başarılı; "
            f"Telegram tahmini gönderilmiyor."
        )

        continue

    consensus = build_consensus(
        votes
    )

    record = {
        "season": SEASON,
        "matchday": match.get(
            "matchday"
        ),
        "match_id": match_id,
        "home_team": home_team,
        "away_team": away_team,
        "match_time": (
            match_utc.astimezone(
                TURKEY_TZ
            ).strftime(
                "%d.%m.%Y %H:%M"
            )
        ),
        "match_utc": (
            match_utc.isoformat()
        ),
        "prediction_created_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "minutes_before_match": round(
            minutes_until,
            1,
        ),
        "context": context,
        "history": history,
        "research": research,
        "ai_votes": [
            {
                "model": v.model,
                "success": v.success,
                "result": v.result,
                "error": v.error,
            }
            for v in votes
        ],
        "consensus": consensus,
        "final_sent": False,
        "result_sent": False,
    }

    prepared_records.append(
        record
    )

# ========================================================
# TELEGRAM GRUPLAMA
# ========================================================

groups: dict[
    str,
    list[dict[str, Any]]
] = {}

for record in prepared_records:

    groups.setdefault(
        kickoff_key(record),
        [],
    ).append(record)

for group_key, records in sorted(
    groups.items()
):

    records.sort(
        key=lambda r: r.get(
            "home_team",
            "",
        )
    )

    message = (
        build_telegram_group_message(
            records,
            test_mode=test_mode,
        )
    )

    image_path = (
        render_match_group_image(
            records,
            test_mode=test_mode,
        )
    )

    try:

        send_telegram_message(
            message
        )

        send_telegram_photo(
            image_path,
            "🖼️ Maç tahmin görseli",
        )

    except Exception as error:

        print(
            f"⚠️ Telegram maç paketi hatası "
            f"({group_key}): {error}"
        )

        continue

    for record in records:

        record[
            "final_sent"
        ] = True

        if not test_mode:

            predictions[
                record[
                    "match_id"
                ]
            ] = record

    print(
        f"✅ {len(records)} maçlık Telegram "
        f"tahmin paketi gönderildi "
        f"({group_key})."
    )

save_predictions(
    predictions
)

if name == "main":
main()
