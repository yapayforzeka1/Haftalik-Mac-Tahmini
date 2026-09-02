from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from ai_pool import run_ai_pool
from consensus_engine import build_consensus
from data_provider import FootballDataClient, FootballDataError, build_team_form, parse_utc
from history_engine import build_team_history, build_ai_performance
from report_engine import build_result_message, build_telegram_message
from research_engine import empty_research, research_match

TURKEY_TZ = ZoneInfo("Europe/Istanbul")
MIN_MINUTES_BEFORE = 45
MAX_MINUTES_BEFORE = 60
MATCHES_FILE = Path("match_predictions.json")
SEASON = "2026/27"


def load_predictions() -> dict:
    if not MATCHES_FILE.exists(): return {}
    try: return json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"⚠️ {MATCHES_FILE} okunamadı: {error}"); return {}


def save_predictions(predictions: dict) -> None:
    temp = MATCHES_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(MATCHES_FILE)


def send_telegram_message(message: str) -> None:
    import requests
    response = requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": message}, timeout=30)
    response.raise_for_status()


def build_standings_map(standings: list[dict]) -> dict[int, dict]:
    result = {}
    for group in standings:
        if group.get("type") != "TOTAL": continue
        for row in group.get("table", []):
            team = row.get("team", {})
            if team.get("id") is not None:
                result[int(team["id"])] = {"position": row.get("position"), "played": row.get("playedGames"),
                    "points": row.get("points"), "goals_for": row.get("goalsFor"), "goals_against": row.get("goalsAgainst")}
    return result


def _actual_outcome(home: int, away: int) -> str:
    return "HOME" if home > away else "AWAY" if home < away else "DRAW"


def update_finished_results(predictions: dict, matches: list[dict]) -> list[dict]:
    changed = []
    by_id = {str(m.get("id")): m for m in matches}
    for match_id, record in predictions.items():
        if record.get("actual"): continue
        match = by_id.get(str(match_id))
        if not match or match.get("status") != "FINISHED": continue
        score = match.get("score", {}).get("fullTime", {})
        if score.get("home") is None or score.get("away") is None: continue
        record["actual"] = {"home": score["home"], "away": score["away"], "status": "FINISHED", "updated_at": datetime.now(timezone.utc).isoformat()}
        predicted = record.get("consensus", {})
        record["exact_score_correct"] = predicted.get("score", "").replace(" ", "") == f"{score['home']}-{score['away']}"
        record["outcome_correct"] = predicted.get("outcome") == _actual_outcome(score["home"], score["away"])
        changed.append(record)
    return changed


def main() -> None:
    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FOOTBALL_DATA_API_KEY"]
    missing = [x for x in required if not os.environ.get(x)]
    if missing: raise RuntimeError(f"Eksik secret: {', '.join(missing)}")

    predictions = load_predictions()
    football = FootballDataClient()
    matches = football.get_matches()
    finished_updates = update_finished_results(predictions, matches)
    for record in finished_updates:
        if not record.get("result_sent"):
            try:
                send_telegram_message(build_result_message(record))
                record["result_sent"] = True
            except Exception as error:
                print(f"⚠️ Sonuç Telegram hatası: {error}")
    if finished_updates: save_predictions(predictions)

    now_utc = datetime.now(timezone.utc)
    upcoming = []
    for match in matches:
        if match.get("status") not in {"SCHEDULED", "TIMED"}: continue
        match_utc = parse_utc(match["utcDate"])
        minutes_until = (match_utc - now_utc).total_seconds() / 60
        if MIN_MINUTES_BEFORE <= minutes_until <= MAX_MINUTES_BEFORE: upcoming.append((match, minutes_until))
    print(f"Toplam {len(matches)} maç; tahmin penceresinde {len(upcoming)} maç.")
    if not upcoming: return

    try: standings_map = build_standings_map(football.get_standings())
    except FootballDataError as error:
        print(f"⚠️ Puan durumu alınamadı: {error}"); standings_map = {}

    research_client = None
    if os.environ.get("GEMINI_API_KEY"):
        from google import genai
        research_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    for match, minutes_until in upcoming:
        match_id = str(match["id"])
        home_team, away_team = match["homeTeam"]["name"], match["awayTeam"]["name"]
        if predictions.get(match_id, {}).get("final_sent"):
            print(f"⏭️ {home_team} - {away_team}: zaten gönderildi."); continue
        match_utc = parse_utc(match["utcDate"])
        context = {"season": SEASON, "matchday": match.get("matchday"), "stage": match.get("stage"), "venue": match.get("venue"),
            "home": {"team_id": int(match["homeTeam"]["id"]), "standings": standings_map.get(int(match["homeTeam"]["id"]))},
            "away": {"team_id": int(match["awayTeam"]["id"]), "standings": standings_map.get(int(match["awayTeam"]["id"]))}}
        try:
            home_matches = football.get_team_matches(context["home"]["team_id"], match_utc)
            away_matches = football.get_team_matches(context["away"]["team_id"], match_utc)
            context["home"]["last_5"] = build_team_form(home_matches, context["home"]["team_id"])
            context["away"]["last_5"] = build_team_form(away_matches, context["away"]["team_id"])
        except FootballDataError as error:
            context["data_warning"] = str(error)
            print(f"⚠️ Son maç verileri alınamadı: {error}")

        history = {"home": build_team_history(predictions, home_team), "away": build_team_history(predictions, away_team),
                   "ai_performance": build_ai_performance(predictions)}
        previous = predictions.get(match_id, {}).get("consensus")

        if research_client:
            try: research = research_match(research_client, home_team, away_team, {"context": context, "history": history})
            except Exception as error:
                print(f"⚠️ Araştırma başarısız; AI yapılandırılmış verilerle devam edecek: {error}")
                research = empty_research(str(error))
        else:
            research = empty_research("GEMINI_API_KEY yok")

        votes = run_ai_pool(home_team, away_team, context, research, history)
        success_count = sum(v.success for v in votes)
        if success_count < 3:
            print(f"🚨 Yetersiz AI başarısı: {success_count}/5; Telegram tahmini gönderilmiyor."); continue
        consensus = build_consensus(votes)
        record = {"season": SEASON, "matchday": match.get("matchday"), "match_id": match_id,
            "home_team": home_team, "away_team": away_team, "match_time": match_utc.astimezone(TURKEY_TZ).strftime("%d.%m.%Y %H:%M"),
            "prediction_created_at": datetime.now(timezone.utc).isoformat(), "minutes_before_match": round(minutes_until, 1),
            "context": context, "history": history, "research": research,
            "ai_votes": [{"model": v.model, "success": v.success, "result": v.result, "error": v.error} for v in votes],
            "consensus": consensus, "final_sent": False, "result_sent": False}
        try: send_telegram_message(build_telegram_message(record))
        except Exception as error:
            print(f"⚠️ Telegram hatası: {error}"); continue
        record["final_sent"] = True
        predictions[match_id] = record
        save_predictions(predictions)
        print(f"✅ {home_team} - {away_team}: Telegram + arşiv tamam.")

    save_predictions(predictions)

if __name__ == "__main__": main()
