import os
import json
import requests

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google import genai


# ============================================================
# AYARLAR
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
FOOTBALL_DATA_API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

TURKEY_TZ = ZoneInfo("Europe/Istanbul")

# GERÇEK SİSTEMDE:
MIN_MINUTES_BEFORE = 30
MAX_MINUTES_BEFORE = 120

MATCHES_FILE = Path("match_predictions.json")

GEMINI_MODEL = "gemini-3.7-flash"


# ============================================================
# GEMINI
# ============================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# KAYIT
# ============================================================

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


# ============================================================
# TELEGRAM
# ============================================================

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


# ============================================================
# FOOTBALL-DATA.ORG
# ============================================================

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


# ============================================================
# MAÇ TARİHİ
# ============================================================

def get_match_datetime(match):

    return datetime.fromisoformat(
        match["utcDate"].replace(
            "Z",
            "+00:00"
        )
    )


# ============================================================
# GEMINI SKOR TAHMİNİ
# ============================================================

def get_prediction(
    home_team,
    away_team
):

    prompt = f"""
Sen profesyonel bir futbol maç analiz uzmanısın.

Şampiyonlar Ligi maçı:

Ev sahibi:
{home_team}

Deplasman:
{away_team}

Bu maç için en olası skor tahminini yap.

SADECE aşağıdaki formatta cevap ver:

HOME_SCORE-AWAY_SCORE

Örnek:

2-1

Başka hiçbir açıklama yazma.
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )

    prediction = response.text.strip()

    return prediction


# ============================================================
# SKOR KONTROLÜ
# ============================================================

def is_valid_prediction(
    prediction
):

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

        if home_score < 0:
            return False

        if away_score < 0:
            return False

        return True

    except Exception:

        return False


# ============================================================
# ANA BOT
# ============================================================

def main():

    matches = get_matches()

    print(
        f"Toplam {len(matches)} "
        "Şampiyonlar Ligi maçı bulundu."
    )

    now_utc = datetime.now(
        timezone.utc
    )

    for match in matches:

        if match.get(
            "status"
        ) != "SCHEDULED":

            continue

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

        match_turkey = (
            match_utc.astimezone(
                TURKEY_TZ
            )
        )

        minutes_until_match = (
            match_utc - now_utc
        ).total_seconds() / 60

        print(
            f"{home_team} - {away_team} | "
            f"Türkiye: "
            f"{match_turkey.strftime('%d.%m.%Y %H:%M')} | "
            f"Kalan: "
            f"{minutes_until_match:.1f} dakika"
        )

        # ----------------------------------------------------
        # MAÇ 2 SAATTEN UZAKSA ATLAMA
        # ----------------------------------------------------

        if (
            minutes_until_match
            > MAX_MINUTES_BEFORE
        ):

            continue

        # ----------------------------------------------------
        # MAÇ 30 DAKİKADAN YAKINSA ATLAMA
        # ----------------------------------------------------

        if (
            minutes_until_match
            < MIN_MINUTES_BEFORE
        ):

            continue

        # ----------------------------------------------------
        # KAYIT OLUŞTUR
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # GEMINI
        # ----------------------------------------------------

        try:

            new_prediction = get_prediction(
                home_team,
                away_team
            )

            print(
                f"Gemini tahmini: "
                f"{new_prediction}"
            )

        except Exception as error:

            print(
                f"Gemini hatası: {error}"
            )

            continue

        # ----------------------------------------------------
        # GEÇERSİZ TAHMİN
        # ----------------------------------------------------

        if not is_valid_prediction(
            new_prediction
        ):

            print(
                "Geçersiz Gemini skoru."
            )

            continue

        previous_prediction = (
            predictions[match_id]
            .get("last_prediction")
        )

        # ----------------------------------------------------
        # 30 DAKİKA CİVARINDA SON TAHMİN
        # ----------------------------------------------------

        if (
            25
            <= minutes_until_match
            <= 45
            and
            not predictions[
                match_id
            ].get(
                "final_sent",
                False
            )
        ):

            message = (
                "🏁 MAÇ ÖNCESİ SON TAHMİN\n\n"
                f"⚽ {home_team} - {away_team}\n\n"
                f"🎯 Tahmin: "
                f"{new_prediction}\n\n"
                f"🇹🇷 Maç saati: "
                f"{match_turkey.strftime('%d.%m.%Y %H:%M')}"
            )

            send_telegram_message(
                message
            )

            predictions[
                match_id
            ]["last_prediction"] = (
                new_prediction
            )

            predictions[
                match_id
            ]["final_sent"] = True

            save_predictions()

            continue

        # ----------------------------------------------------
        # İLK TAHMİN
        # ----------------------------------------------------

        if previous_prediction is None:

            message = (
                "⚽ ŞAMPİYONLAR LİGİ TAHMİNİ\n\n"
                f"🏟️ {home_team} - {away_team}\n\n"
                f"🎯 Tahmin: "
                f"{new_prediction}\n\n"
                f"🇹🇷 Maç saati: "
                f"{match_turkey.strftime('%d.%m.%Y %H:%M')}"
            )

            send_telegram_message(
                message
            )

            predictions[
                match_id
            ]["last_prediction"] = (
                new_prediction
            )

            save_predictions()

            continue

        # ----------------------------------------------------
        # SKOR DEĞİŞTİYSE MESAJ
        # ----------------------------------------------------

        if (
            new_prediction
            != previous_prediction
        ):

            message = (
                "🔄 TAHMİN GÜNCELLENDİ\n\n"
                f"⚽ {home_team} - {away_team}\n\n"
                f"❌ Önceki: "
                f"{previous_prediction}\n\n"
                f"✅ Yeni: "
                f"{new_prediction}\n\n"
                f"🇹🇷 Maç saati: "
                f"{match_turkey.strftime('%d.%m.%Y %H:%M')}"
            )

            send_telegram_message(
                message
            )

            predictions[
                match_id
            ]["last_prediction"] = (
                new_prediction
            )

            save_predictions()


# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":
    main()
