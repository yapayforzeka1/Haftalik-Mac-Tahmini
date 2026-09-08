from __future__ import annotations

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

# ============================================================
# MAÇ TAHMİN ZAMAN AYARLARI
# ============================================================

# Tahmin gönderimi için izin verilen pencere.
#
# Örnek:
# Maç 22:00 ise:
#
# 20:45 -> ilk uygun çalışma
# 20:50
# 20:55
# ...
# 21:45 -> son uygun çalışma
#
MIN_MINUTES_BEFORE = 15
MAX_MINUTES_BEFORE = 75

# Botun maçları daha erken keşfedebilmesi için kullanılan pencere.
#
# Bu değer tahmin gönderim penceresini değiştirmez.
# Sadece teşhis / aday keşfi için kullanılır.
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
    """Bot 1: maç tahmini ve maç sonucu mesajları."""

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
    """Bot 2: haftalık ve genel AI performans raporları."""

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

            # ------------------------------------------------
            # ÖNEMLİ:
            #
            # Artık burada doğrudan 15-75 dakikayı filtrelemiyoruz.
            #
            # Önce 180 dakikalık keşif penceresine giren
            # gelecek maçları alıyoruz.
            #
            # Böylece bot maçı daha erken görebiliyor.
            # Ancak AI tahmini aşağıda SADECE 15-75 dakika
            # arasında çalıştırılıyor.
            # ------------------------------------------------

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
    """
    Tahmin penceresinde maç bulunamadığında canlı API verisini
    teşhis etmek için en yakın gelecek maçları loglar.
    """

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

    """Build deterministic sample data for Telegram weekly-report testing."""

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

    # --------------------------------------------------------
    # HAFTALIK RAPOR
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # NORMAL MODDA:
    #
    # _upcoming_matches artık 0-180 dakika arasındaki
    # gelecek maçları buluyor.
    #
    # FAKAT AI TAHMİNİ SADECE 15-75 DAKİKA ARASINDA
    # çalıştırılacak.
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # AI TAHMİN PENCERESİ FİLTRESİ
    # --------------------------------------------------------

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

        # ----------------------------------------------------
        # RESMİ İLK 11 KONTROLÜ
        # ----------------------------------------------------

        official_xi_context = None

        try:

            details = (
                football.get_match_details(
                    int(match_id)
                )
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

                official_xi_context = {
                    "status": "ANNOUNCED",
                    "home": home_xi,
                    "away": away_xi,
                    "source": (
                        "football-data.org "
                        "match lineup"
                    ),
                }

                context[
                    "official_xi"
                ] = official_xi_context

                print(
                    f"✅ {home_team} - {away_team}: "
                    f"resmi ilk 11 doğrulandı."
                )

            else:

                print(
                    f"⏳ {home_team} - {away_team}: "
                    f"resmi ilk 11 henüz tam değil "
                    f"({len(home_xi)}/11 - "
                    f"{len(away_xi)}/11)."
                )

        except FootballDataError as error:

            context[
                "official_xi_warning"
            ] = str(error)

            print(
                f"⚠️ Resmi XI football-data.org "
                f"üzerinden alınamadı: {error}"
            )

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

        # ----------------------------------------------------
        # ARAŞTIRMA
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # RESEARCH KATMANINDAN XI KONTROLÜ
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # XI YOKSA TAHMİN GÖNDERME
        # ----------------------------------------------------

        if (
            not test_mode
            and not (
                official_xi_context
                or research_xi_announced
            )
        ):

            print(
                f"⏳ {home_team} - {away_team}: "
                f"resmi ilk 11 henüz doğrulanmadı; "
                f"tahmin ertelendi."
            )

            continue

        # ----------------------------------------------------
        # AI POOL
        # ----------------------------------------------------

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

    # --------------------------------------------------------
    # TELEGRAM GRUPLAMA
    # --------------------------------------------------------

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


if __name__ == "__main__":
    main()
