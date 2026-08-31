import os
import json
import requests

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


# ============================================================
# AYARLAR
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
FOOTBALL_DATA_API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]

TURKEY_TZ = ZoneInfo("Europe/Istanbul")

# Tahmin penceresi
MIN_MINUTES_BEFORE = 30
MAX_MINUTES_BEFORE = 120

# Maç bilgilerinin tutulacağı dosya
MATCHES_FILE = Path("match_predictions.json")


# ============================================================
# KAYIT DOSYASINI OKU
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

    except (json.JSONDecodeError, OSError):

        return {}


predictions = load_predictions()


# ============================================================
# KAYDET
# ============================================================

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
# TELEGRAM MESAJI
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
# ŞAMPİYONLAR LİGİ MAÇLARINI GETİR
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

    data = response.json()

    return data.get("matches", [])


# ============================================================
# MAÇ ZAMANI
# ============================================================

def get_match_datetime(match):

    utc_date = match["utcDate"]

    return datetime.fromisoformat(
        utc_date.replace("Z", "+00:00")
    )


# ============================================================
# ANA SİSTEM
# ============================================================

def main():

    matches = get_matches()

    print(
        f"Toplam {len(matches)} "
        f"Şampiyonlar Ligi maçı bulundu."
    )

    now_utc = datetime.now(timezone.utc)

    for match in matches:

        # Sadece planlanmış maçlar
        if match.get("status") != "SCHEDULED":
            continue

        match_id = str(match["id"])

        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]

        match_utc = get_match_datetime(match)

        match_turkey = match_utc.astimezone(TURKEY_TZ)

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

        # ====================================================
        # MAÇTAN 30 DAKİKADAN AZ KALDIYSA ARTIK ANALİZ YOK
        # ====================================================

        if minutes_until_match < MIN_MINUTES_BEFORE:

            continue

        # ====================================================
        # MAÇA 2 SAATTEN FAZLA VARSA ANALİZ YOK
        # ====================================================

        if minutes_until_match > MAX_MINUTES_BEFORE:

            continue

        # ====================================================
        # MAÇ 1-2 SAAT İÇERİSİNDE
        # ====================================================

        if match_id not in predictions:

            predictions[match_id] = {
                "home_team": home_team,
                "away_team": away_team,
                "match_time": match_turkey.strftime(
                    "%d.%m.%Y %H:%M"
                ),
                "last_prediction": None,
                "last_prediction_time": None,
                "last_message_type": None
            }

        # ====================================================
        # ŞİMDİLİK TEST
        # ====================================================

        # Gemini henüz burada kullanılmıyor.
        # Geçici test skoru:

        new_prediction = "2-1"

        previous_prediction = predictions[
            match_id
        ].get("last_prediction")

        # ====================================================
        # MAÇTAN TAM OLARAK 30 DAKİKA ÖNCEKİ
        # SON TAHMİN
        # ====================================================

        final_prediction_window = (
            25 <= minutes_until_match <= 45
        )

        if final_prediction_window:

            message = (
                "🏁 MAÇ ÖNCESİ SON TAHMİN\n\n"
                f"⚽ {home_team} - {away_team}\n\n"
                f"🎯 Tahmin: {new_prediction}\n\n"
                f"🇹🇷 Maç saati: "
                f"{match_turkey.strftime('%d.%m.%Y %H:%M')}\n\n"
                "⏰ Maç başlamadan yaklaşık "
                "30 dakika önce."
            )

            send_telegram_message(message)

            predictions[match_id][
                "last_prediction"
            ] = new_prediction

            predictions[match_id][
                "last_prediction_time"
            ] = datetime.now(
                timezone.utc
            ).isoformat()

            predictions[match_id][
                "last_message_type"
            ] = "final"

            save_predictions()

            continue

        # ====================================================
        # İLK TAHMİN
        # ====================================================

        if previous_prediction is None:

            message = (
                "⚽ ŞAMPİYONLAR LİGİ TAHMİNİ\n\n"
                f"🏟️ {home_team} - {away_team}\n\n"
                f"🎯 Tahmin: {new_prediction}\n\n"
                f"🇹🇷 Maç saati: "
                f"{match_turkey.strftime('%d.%m.%Y %H:%M')}"
            )

            send_telegram_message(message)

            predictions[match_id][
                "last_prediction"
            ] = new_prediction

            predictions[match_id][
                "last_prediction_time"
            ] = datetime.now(
                timezone.utc
            ).isoformat()

            predictions[match_id][
                "last_message_type"
            ] = "initial"

            save_predictions()

            continue

        # ====================================================
        # SKOR DEĞİŞTİYSE GÜNCELLE
        # ====================================================

        if new_prediction != previous_prediction:

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

            send_telegram_message(message)

            predictions[match_id][
                "last_prediction"
            ] = new_prediction

            predictions[match_id][
                "last_prediction_time"
            ] = datetime.now(
                timezone.utc
            ).isoformat()

            predictions[match_id][
                "last_message_type"
            ] = "update"

            save_predictions()


# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":

    main()
