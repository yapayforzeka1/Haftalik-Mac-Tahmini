"""Token-free visual smoke test for approved Champions League Telegram cards.
No AI provider, football provider or research API is called.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from match_report import render_match_group_image


def vote(model, outcome, score, confidence, reason):
    return {"model": model, "success": True, "result": {"outcome": outcome, "score": score, "confidence": confidence, "short_reason": reason}}


def record(mid, home, away, kickoff, score="2-1"):
    return {
        "match_id": str(mid), "home_team": home, "away_team": away,
        "match_utc": kickoff.isoformat(), "stage": "LEAGUE_STAGE", "test_mode": True,
        "consensus_min_successful": 3, "total_ai": 5,
        "ai_votes": [
            vote("Gemini 3.6 Flash", "HOME", score, 72, f"{home} son maçlardaki hücum üretkenliğiyle öne çıkıyor."),
            vote("Mistral Small Latest", "HOME", score, 69, f"{home} orta saha kontrolünde avantajlı görünüyor."),
            vote("Groq Qwen 3.8 27B", "HOME", score, 71, f"{away} geçiş savunmasında alan bırakabiliyor."),
            {"model":"Cohere Command A+", "success":False, "error":"OFFLINE_TEST"},
            {"model":"Groq GPT-OSS 120B", "success":False, "error":"OFFLINE_TEST"},
        ],
        "context": {
            "official_xi": {"status":"NOT_ANNOUNCED"},
            "predicted_xi": {},
            "home": {"last_5":[1,2,3], "standings":{"position":3}},
            "away": {"last_5":[1,2,3], "standings":{"position":7}},
        },
        "research": {"status":"EMPTY"},
    }


def send_photo(path: Path, caption: str):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    import requests
    with path.open("rb") as fh:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={"chat_id":chat,"caption":caption}, files={"photo":fh}, timeout=60)
        r.raise_for_status()


def main():
    kickoff = datetime.now(timezone.utc) + timedelta(days=1)
    single = render_match_group_image([record(900001,"Galatasaray","Liverpool",kickoff)], test_mode=True)
    multi_records = [
        record(900011,"Galatasaray","Liverpool",kickoff,"2-1"),
        record(900012,"Real Madrid","Juventus",kickoff,"2-0"),
        record(900013,"Arsenal","Bayern Münih",kickoff,"1-2"),
        record(900014,"Inter","Benfica",kickoff,"2-1"),
    ]
    multi = render_match_group_image(multi_records, test_mode=True)
    send_photo(single, "🧪 TOKEN KULLANMADAN GÖRSEL TESTİ — Tek maç")
    send_photo(multi, "🧪 TOKEN KULLANMADAN GÖRSEL TESTİ — Çoklu maç")
    print(f"OFFLINE_VISUAL_TEST_OK single={single} multi={multi} AI/API token kullanılmadı.")

if __name__ == "__main__":
    main()
