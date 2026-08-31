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

MIN_MINUTES_BEFORE = 60
MAX_MINUTES_BEFORE = 120

SENT_MATCHES_FILE = Path("sent_matches.json")


# ============================================================
# GÖNDERİLMİŞ MAÇLARI OKU
# ============================================================

def load_sent_matches():

    if not SENT_MATCHES_FILE.exists():
        return []

    try:
        with open(
            SENT_MATCHES_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except (json.JSONDecodeError, OSError):
        return []


sent_matches = load_sent_matches()


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
# MAÇLARI GETİR
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
# MAÇ ZAMANINI AL
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

    found_match = False

    for match in matches:

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

        # Daha önce gönderilmişse tekrar gönderme
        if match_id in sent_matches:
            continue

        # ====================================================
        # 1-2 SAAT KONTROLÜ
        # ====================================================

        if (
            MIN_MINUTES_BEFORE
            <= minutes_until_match
            <= MAX_MINUTES_BEFORE
        ):

            found_match = True

            message = (
                "⚽ ŞAMPİYONLAR LİGİ TEST\n\n"
                f"🏟️ {home_team} - {away_team}\n\n"
                f"🇹🇷 Maç saati: "
                f"{match_turkey.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"⏰ Maça yaklaşık "
                f"{minutes_until_match:.0f} dakika kaldı.\n\n"
                "✅ 1-2 saatlik tahmin penceresi "
                "başarıyla tespit edildi."
            )

            send_telegram_message(message)

            print(
                f"Telegram mesajı gönderildi: "
                f"{home_team} - {away_team}"
            )

            # Maçı kaydet
            sent_matches.append(match_id)


    # ========================================================
    # GÖNDERİLMİŞ MAÇLARI KAYDET
    # ========================================================

    with open(
        SENT_MATCHES_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            sent_matches,
            file,
            ensure_ascii=False,
            indent=2
        )


    # ========================================================
    # UYGUN MAÇ YOKSA
    # ========================================================

    if not found_match:

        print(
            "Şu anda 1-2 saat içinde başlayacak "
            "yeni bir maç bulunamadı."
        )


# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":
    main()
