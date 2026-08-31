import os
import json
import requests

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google import genai


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
FOOTBALL_DATA_API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

TURKEY_TZ = ZoneInfo("Europe/Istanbul")

# Maçtan yaklaşık 50 dakika önce gönderim yapılır.
# GitHub Actions çalışma zamanına göre küçük tolerans bırakılır.
MIN_MINUTES_BEFORE = 45
MAX_MINUTES_BEFORE = 60

MATCHES_FILE = Path("match_predictions.json")

GEMINI_MODEL = "gemini-3.7-flash"

client = genai.Client(
    api_key=GEMINI_API_KEY
)


def load_predictions():

    if not MATCHES_FILE.exists():
        return {}

    try:
        with open(
            MATCHES_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except Exception:
        return {}


predictions = load_predictions()


def save_predictions():

    with open(
        MATCHES_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            predictions,
            file,
            ensure_ascii=False,
            indent=2
        )


def send_telegram_message(message):

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=30
    )

    response.raise_for_status()


def get_matches():

    url = (
        "https://api.football-data.org/v4/"
        "competitions/CL/matches"
    )

    headers = {
        "X-Auth-Token": FOOTBALL_DATA_API_KEY
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response.json().get(
        "matches",
        []
    )


def get_match_datetime(match):

    return datetime.fromisoformat(
        match["utcDate"].replace(
            "Z",
            "+00:00"
        )
    )


def get_prediction(
    home_team,
    away_team
):

    prompt = f"""
Sen profesyonel bir futbol skor tahmin uzmanısın.

Şampiyonlar Ligi maçı:

Ev sahibi: {home_team}
Deplasman: {away_team}

Bu maç için en olası skor tahminini belirle.

SADECE skor döndür.

Format:

2-1

Başka hiçbir şey yazma.
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )

    return response.text.strip()


def is_valid_prediction(prediction):

    try:

        parts = prediction.split("-")

        if len(parts) != 2:
            return False

        home_score = int(
            parts[0].strip()
        )

        away_score = int(
            parts[1].strip()
        )

        return (
            home_score >= 0
            and away_score >= 0
        )

    except Exception:

        return False


def main():

    matches = get_matches()

    now_utc = datetime.now(
        timezone.utc
    )

    upcoming_matches = []

    for match in matches:

        status = match.get(
            "status",
            "UNKNOWN"
        )

        if status not in (
            "SCHEDULED",
            "TIMED"
        ):
            continue

        match_utc = get_match_datetime(
            match
        )

        minutes_until_match = (
            match_utc - now_utc
        ).total_seconds() / 60

        if (
            MIN_MINUTES_BEFORE
            <= minutes_until_match
            <= MAX_MINUTES_BEFORE
        ):

            upcoming_matches.append(
                match
            )

    print(
        f"Toplam {len(matches)} maç bulundu."
    )

    print(
        f"50 dakika penceresinde "
        f"{len(upcoming_matches)} maç var."
    )

    if not upcoming_matches:

        print(
            "Şu anda analiz edilecek maç yok."
        )

        return

    for match in upcoming_matches:

        match_id = str(
            match["id"]
        )

        home_team = match[
            "homeTeam"
        ]["name"]

        away_team = match[
            "awayTeam"
        ]["name"]

        match_utc = get_match_datetime(
            match
        )

        match_turkey = match_utc.astimezone(
            TURKEY_TZ
        )

        minutes_until_match = (
            match_utc - now_utc
        ).total_seconds() / 60

        print(
            f"Analiz: {home_team} - "
            f"{away_team} | "
            f"{minutes_until_match:.1f} dk kaldı"
        )

        if match_id not in predictions:

            predictions[match_id] = {
                "home_team": home_team,
                "away_team": away_team,
                "match_time": match_turkey.strftime(
                    "%d.%m.%Y %H:%M"
                ),
                "last_prediction": None,
                "final_sent": False
            }

        if predictions[match_id].get(
            "final_sent",
            False
        ):

            print(
                "Bu maç için mesaj zaten gönderilmiş."
            )

            continue

        try:

            new_prediction = get_prediction(
                home_team,
                away_team
            )

            print(
                f"Tahmin: {new_prediction}"
            )

        except Exception as error:

            print(
                f"Gemini hatası: {error}"
            )

            continue

        if not is_valid_prediction(
            new_prediction
        ):

            print(
                "Geçersiz Gemini tahmini."
            )

            continue

        message = (
            "🏁 MAÇ ÖNCESİ SON TAHMİN\n\n"
            f"⚽ {home_team} - {away_team}\n\n"
            f"🎯 Tahmin: {new_prediction}\n\n"
            f"🇹🇷 Maç saati: "
            f"{match_turkey.strftime('%d.%m.%Y %H:%M')}"
        )

        try:

            send_telegram_message(
                message
            )

        except Exception as error:

            print(
                f"Telegram hatası: {error}"
            )

            continue

        predictions[match_id][
            "last_prediction"
        ] = new_prediction

        predictions[match_id][
            "final_sent"
        ] = True

        save_predictions()

        print(
            "Telegram mesajı gönderildi."
        )


if __name__ == "__main__":
    main()
