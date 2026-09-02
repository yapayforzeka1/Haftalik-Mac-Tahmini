from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

from ai_pool import run_ai_pool
from consensus_engine import build_consensus
from data_provider import FootballDataClient, FootballDataError, build_team_form, parse_utc
from history_engine import build_ai_performance, build_team_history, grade_record
from report_engine import build_result_message, build_telegram_message
from research_engine import empty_research, research_match
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
MIN_MINUTES_BEFORE = 45
MAX_MINUTES_BEFORE = 60
MATCHES_FILE = Path("match_predictions.json")
WEEKLY_SCHEDULE_FILE = Path("weekly_schedule.json")
SEASON = "2026/27"
TERMINAL_STATUSES = {"POSTPONED", "CANCELLED", "SUSPENDED", "ABANDONED"}


def load_predictions() -> dict[str, Any]:
    if not MATCHES_FILE.exists():
        return {}
    try:
        return json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"⚠️ {MATCHES_FILE} okunamadı: {error}")
        return {}


def save_predictions(predictions: dict[str, Any]) -> None:
    temp = MATCHES_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(MATCHES_FILE)


def send_telegram_message(message: str) -> None:
    import requests
    response = requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": message},
        timeout=30,
    )
    response.raise_for_status()


def send_telegram_photo(path: Path, caption: str | None = None) -> None:
    import requests
    with path.open("rb") as photo:
        data = {"chat_id": os.environ["TELEGRAM_CHAT_ID"]}
        if caption:
            data["caption"] = caption
        response = requests.post(
            f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendPhoto",
            data=data,
            files={"photo": photo},
            timeout=60,
        )
    response.raise_for_status()


def build_standings_map(standings: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for group in standings:
        if group.get("type") != "TOTAL":
            continue
        for row in group.get("table", []):
            team = row.get("team", {})
            if team.get("id") is not None:
                result[int(team["id"])] = {
                    "position": row.get("position"),
                    "played": row.get("playedGames"),
                    "points": row.get("points"),
                    "goals_for": row.get("goalsFor"),
                    "goals_against": row.get("goalsAgainst"),
                }
    return result


def update_finished_results(predictions: dict[str, Any], matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changed = []
    by_id = {str(m.get("id")): m for m in matches}
    for match_id, record in predictions.items():
        if record.get("actual"):
            continue
        match = by_id.get(str(match_id))
        if not match or match.get("status") != "FINISHED":
            continue
        score = match.get("score", {}).get("fullTime", {})
        if score.get("home") is None or score.get("away") is None:
            continue
        record["actual"] = {
            "home": score["home"],
            "away": score["away"],
            "status": "FINISHED",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        grade_record(record)
        changed.append(record)
    return changed


def _upcoming_matches(matches: list[dict[str, Any]], now_utc: datetime, test_mode: bool) -> list[tuple[dict[str, Any], float]]:
    candidates = []
    for match in matches:
        if match.get("status") not in {"SCHEDULED", "TIMED"}:
            continue
        match_utc = parse_utc(match["utcDate"])
        minutes_until = (match_utc - now_utc).total_seconds() / 60
        if test_mode:
            if minutes_until > 0:
                candidates.append((match, minutes_until))
        elif MIN_MINUTES_BEFORE <= minutes_until <= MAX_MINUTES_BEFORE:
            candidates.append((match, minutes_until))
    if test_mode and candidates:
        candidates.sort(key=lambda item: item[1])
        return candidates[:1]
    return candidates


def _load_weekly_schedule() -> dict[str, str]:
    if not WEEKLY_SCHEDULE_FILE.exists():
        return {}
    try:
        return json.loads(WEEKLY_SCHEDULE_FILE.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"⚠️ {WEEKLY_SCHEDULE_FILE} okunamadı: {error}")
        return {}


def _save_weekly_schedule(data: dict[str, str]) -> None:
    temp = WEEKLY_SCHEDULE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(WEEKLY_SCHEDULE_FILE)


def _planned_last_kickoff_by_matchday(matches: list[dict[str, Any]]) -> dict[int, datetime]:
    """Capture the original cutoff so postponements/reschedules do not move the report."""
    schedule = _load_weekly_schedule()
    result: dict[int, datetime] = {}
    changed = False

    for match in matches:
        md = match.get("matchday")
        if md is None:
            continue
        try:
            matchday = int(md)
            kickoff = parse_utc(match["utcDate"])
        except (ValueError, TypeError, KeyError):
            continue

        key = str(matchday)
        if key in schedule:
            try:
                result[matchday] = datetime.fromisoformat(schedule[key].replace("Z", "+00:00"))
                continue
            except ValueError:
                pass

        # A postponed/cancelled fixture must not establish or move the cutoff.
        if match.get("status") in TERMINAL_STATUSES:
            continue
        if matchday not in result or kickoff > result[matchday]:
            result[matchday] = kickoff

    for matchday, kickoff in result.items():
        key = str(matchday)
        if key not in schedule:
            schedule[key] = kickoff.isoformat()
            changed = True

    if changed:
        _save_weekly_schedule(schedule)
    return result



def _build_report_test_data() -> tuple[dict[str, Any], dict[str, Any]]:
    """Build deterministic sample data for Telegram weekly-report testing.

    This data is deliberately separate from the real prediction archive and is
    never written to match_predictions.json or weekly_reports.json.
    """
    def record(match_id: str, matchday: int, home: str, away: str, actual_h: int, actual_a: int,
               scores: list[str], consensus_score: str) -> dict[str, Any]:
        votes = []
        for model, score in zip(MODEL_ORDER, scores):
            ph, pa = (int(x) for x in score.split("-"))
            pred_outcome = "HOME" if ph > pa else "AWAY" if ph < pa else "DRAW"
            actual_outcome = "HOME" if actual_h > actual_a else "AWAY" if actual_h < actual_a else "DRAW"
            exact = score == f"{actual_h}-{actual_a}"
            outcome_correct = pred_outcome == actual_outcome
            points = 5 if exact or (pred_outcome == "DRAW" and actual_outcome == "DRAW") else 3 if outcome_correct else 0
            votes.append({
                "model": model,
                "success": True,
                "result": {"score": score, "outcome": pred_outcome},
                "points": points,
                "exact_score_correct": exact,
                "outcome_correct": outcome_correct,
            })

        ch, ca = (int(x) for x in consensus_score.split("-"))
        c_outcome = "HOME" if ch > ca else "AWAY" if ch < ca else "DRAW"
        a_outcome = "HOME" if actual_h > actual_a else "AWAY" if actual_h < actual_a else "DRAW"
        c_exact = consensus_score == f"{actual_h}-{actual_a}"
        c_outcome_correct = c_outcome == a_outcome
        c_points = 5 if c_exact or (c_outcome == "DRAW" and a_outcome == "DRAW") else 3 if c_outcome_correct else 0
        return {
            "season": SEASON,
            "matchday": matchday,
            "match_id": match_id,
            "home_team": home,
            "away_team": away,
            "match_time": "08.09.2026 19:45",
            "match_utc": "2026-09-08T16:45:00+00:00",
            "actual": {"home": actual_h, "away": actual_a},
            "ai_votes": votes,
            "consensus": {"score": consensus_score, "outcome": c_outcome},
            "consensus_points": c_points,
            "exact_score_correct": c_exact,
            "outcome_correct": c_outcome_correct,
        }

    md1 = [
        record("test-101", 1, "Club Brugge", "Aston Villa", 3, 1, ["3-1", "2-1", "3-1", "3-1", "1-2"], "3-1"),
        record("test-102", 1, "Real Madrid", "Inter", 2, 0, ["2-0", "2-1", "1-0", "2-0", "2-0"], "2-0"),
        record("test-103", 1, "Arsenal", "PSG", 1, 1, ["1-1", "2-1", "0-0", "1-1", "2-2"], "1-1"),
        record("test-104", 1, "Bayern", "Barcelona", 3, 2, ["3-2", "2-1", "3-1", "1-2", "3-2"], "3-2"),
    ]
    md2 = [
        record("test-201", 2, "Liverpool", "Milan", 2, 1, ["2-1", "1-1", "2-0", "2-1", "3-1"], "2-1"),
        record("test-202", 2, "Barcelona", "Dortmund", 1, 2, ["1-0", "1-2", "2-1", "1-2", "0-1"], "1-2"),
        record("test-203", 2, "City", "Napoli", 2, 2, ["2-1", "1-1", "2-2", "3-2", "0-0"], "2-2"),
        record("test-204", 2, "PSG", "Benfica", 3, 0, ["3-0", "2-0", "3-1", "3-0", "2-0"], "3-0"),
    ]

    predictions = {r["match_id"]: r for r in md1 + md2}
    planned = [{"id": r["match_id"], "matchday": r["matchday"], "status": "FINISHED",
                "homeTeam": {"name": r["home_team"]}, "awayTeam": {"name": r["away_team"]}} for r in md1 + md2]
    reports = {
        "1": build_weekly_snapshot(predictions, 1, planned),
        "2": build_weekly_snapshot(predictions, 2, planned),
    }
    return predictions, reports


def run_weekly_report_test() -> None:
    """Send sample weekly + general images to Telegram without touching archives."""
    predictions, reports = _build_report_test_data()
    weekly_image = render_weekly_image(reports["2"], predictions)
    general_image = render_general_image(reports)
    send_telegram_photo(weekly_image, "🧪 TEST • Matchday 2 — Haftalık Performans")
    send_telegram_photo(general_image, "🧪 TEST • Genel Performans")
    print("✅ Haftalık + genel performans görselleri TEST olarak Telegram'a gönderildi.")


def maybe_send_weekly_reports(predictions: dict[str, Any], matches: list[dict[str, Any]], now_utc: datetime) -> bool:
    """
    Matchday raporu, o matchday'in planlanan son maç başlangıcından 1 saat sonra hazırlanır.
    Ertelenen/iptal edilen maçlar raporu bloke etmez; o anda sonucu bulunan tahminler değerlendirilir.
    Bir matchday raporlandıktan sonra snapshot tekrar yazılmaz.
    """
    weekly_reports = load_weekly_reports()
    last_kickoffs = _planned_last_kickoff_by_matchday(matches)
    changed = False

    for matchday, last_kickoff in sorted(last_kickoffs.items()):
        if now_utc < last_kickoff + timedelta(hours=1):
            continue
        key = str(matchday)
        if key in weekly_reports:
            continue

        snapshot = weekly_reports.get(key) or build_weekly_snapshot(predictions, matchday, matches)
        snapshot.setdefault("last_planned_kickoff", last_kickoffs[matchday].isoformat())
        weekly_reports[key] = snapshot
        changed = True

        if not snapshot.get("telegram_sent"):
            weekly_image = render_weekly_image(snapshot, predictions)
            general_image = render_general_image(weekly_reports)
            try:
                if not snapshot.get("weekly_photo_sent"):
                    send_telegram_photo(weekly_image, f"🏆 Matchday {matchday} — Haftalık Performans")
                    snapshot["weekly_photo_sent"] = True
                    save_weekly_reports(weekly_reports)

                if not snapshot.get("general_photo_sent"):
                    send_telegram_photo(general_image, "🏆 Genel Performans")
                    snapshot["general_photo_sent"] = True
                    save_weekly_reports(weekly_reports)

                snapshot["telegram_sent"] = True
                save_weekly_reports(weekly_reports)
                print(f"✅ Matchday {matchday} haftalık + genel performans raporları Telegram'a gönderildi.")
            except Exception as error:
                save_weekly_reports(weekly_reports)
                print(f"⚠️ Haftalık rapor Telegram hatası: {error}")
        else:
            save_weekly_reports(weekly_reports)

    return changed


def main() -> None:
    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FOOTBALL_DATA_API_KEY"]
    missing = [x for x in required if not os.environ.get(x)]
    if missing:
        raise RuntimeError(f"Eksik secret: {', '.join(missing)}")

    report_test_mode = os.environ.get("REPORT_TEST_MODE", "false").lower() == "true"
    if report_test_mode:
        print("🧪 HAFTALIK RAPOR TEST MODU AKTİF")
        run_weekly_report_test()
        return

    predictions = load_predictions()
    football = FootballDataClient()
    matches = football.get_matches()
    now_utc = datetime.now(timezone.utc)

    finished_updates = update_finished_results(predictions, matches)
    for record in finished_updates:
        if not record.get("result_sent"):
            try:
                send_telegram_message(build_result_message(record))
                record["result_sent"] = True
            except Exception as error:
                print(f"⚠️ Sonuç Telegram hatası: {error}")
    if finished_updates:
        save_predictions(predictions)

    # Weekly report check is independent from the 45-60 minute prediction window.
    try:
        maybe_send_weekly_reports(predictions, matches, now_utc)
    except Exception as error:
        print(f"⚠️ Haftalık rapor oluşturma hatası: {error}")

    test_mode = os.environ.get("TEST_MODE", "false").lower() == "true"
    upcoming = _upcoming_matches(matches, now_utc, test_mode)
    if test_mode:
        print("🧪 TEST MODU AKTİF")
        print("45-60 dakika filtresi bypass edilecek; en yakın gelecek maç kullanılacak.")
    print(f"Toplam {len(matches)} maç; {'TEST MODUNDA' if test_mode else 'tahmin penceresinde'} {len(upcoming)} maç seçildi.")
    if not upcoming:
        save_predictions(predictions)
        return

    try:
        standings_map = build_standings_map(football.get_standings())
    except FootballDataError as error:
        print(f"⚠️ Puan durumu alınamadı: {error}")
        standings_map = {}

    research_client = None
    if os.environ.get("GEMINI_API_KEY"):
        from google import genai
        research_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    for match, minutes_until in upcoming:
        match_id = str(match["id"])
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]
        if not test_mode and predictions.get(match_id, {}).get("final_sent"):
            print(f"⏭️ {home_team} - {away_team}: zaten gönderildi.")
            continue

        match_utc = parse_utc(match["utcDate"])
        context = {
            "season": SEASON,
            "matchday": match.get("matchday"),
            "stage": match.get("stage"),
            "venue": match.get("venue"),
            "home": {"team_id": int(match["homeTeam"]["id"]), "standings": standings_map.get(int(match["homeTeam"]["id"]))},
            "away": {"team_id": int(match["awayTeam"]["id"]), "standings": standings_map.get(int(match["awayTeam"]["id"]))},
        }
        try:
            home_matches = football.get_team_matches(context["home"]["team_id"], match_utc)
            away_matches = football.get_team_matches(context["away"]["team_id"], match_utc)
            context["home"]["last_5"] = build_team_form(home_matches, context["home"]["team_id"])
            context["away"]["last_5"] = build_team_form(away_matches, context["away"]["team_id"])
        except FootballDataError as error:
            context["data_warning"] = str(error)
            print(f"⚠️ Son maç verileri alınamadı: {error}")

        history = {
            "home": build_team_history(predictions, home_team),
            "away": build_team_history(predictions, away_team),
            "ai_performance": build_ai_performance(predictions),
        }

        if research_client:
            try:
                research = research_match(research_client, home_team, away_team, {"context": context, "history": history})
            except Exception as error:
                print(f"⚠️ Araştırma başarısız; AI yapılandırılmış verilerle devam edecek: {error}")
                research = empty_research(str(error))
        else:
            research = empty_research("GEMINI_API_KEY yok")

        votes = run_ai_pool(home_team, away_team, context, research, history)
        success_count = sum(v.success for v in votes)
        if success_count < 3:
            print(f"🚨 Yetersiz AI başarısı: {success_count}/5; Telegram tahmini gönderilmiyor.")
            continue

        consensus = build_consensus(votes)
        record = {
            "season": SEASON,
            "matchday": match.get("matchday"),
            "match_id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "match_time": match_utc.astimezone(TURKEY_TZ).strftime("%d.%m.%Y %H:%M"),
            "match_utc": match_utc.isoformat(),
            "prediction_created_at": datetime.now(timezone.utc).isoformat(),
            "minutes_before_match": round(minutes_until, 1),
            "context": context,
            "history": history,
            "research": research,
            "ai_votes": [{"model": v.model, "success": v.success, "result": v.result, "error": v.error} for v in votes],
            "consensus": consensus,
            "final_sent": False,
            "result_sent": False,
        }

        message = build_telegram_message(record)
        if test_mode:
            message = "🧪 TEST MODU\n\n" + message

        try:
            send_telegram_message(message)
        except Exception as error:
            print(f"⚠️ Telegram hatası: {error}")
            continue

        record["final_sent"] = True
        if not test_mode:
            predictions[match_id] = record
            save_predictions(predictions)
        print(f"✅ {home_team} - {away_team}: Telegram {'testi' if test_mode else '+ arşiv'} tamam.")

    save_predictions(predictions)


if __name__ == "__main__":
    main()
