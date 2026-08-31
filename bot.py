import os
import json
import requests

from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


# ============================================================
# AYARLAR
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
FOOTBALL_DATA_API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]

# Türkiye saat dilimi
TURKEY_TZ = ZoneInfo("Europe/Istanbul")

# Maçtan ne kadar önce tahmin yapılacak?
MIN_MINUTES_BEFORE = 60
MAX_MINUTES_BEFORE = 120

# Daha önce işlenen maçları tutacağımız dosya
SENT_MATCHES_FILE = Path("sent_matches.json")


# ============================================================
# DAHA ÖNCE İŞLENEN MAÇLARI OKU
# ============================================================

def load_sent_matches():
    if not SENT_MATCHES_FILE.exists():
        return []

    try:
        with open(SENT_MATCHES_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    except (json.JSONDecodeError, OSError):
        return []


sent_matches = load_sent_matches()


# ============================================================
# TELEGRAM'A MESAJ GÖNDER
# ============================================================

def send_telegram_message(message):
    telegram_url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        telegram_url,
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

def get_champions_league_matches():

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
# MAÇ KİMLİĞİ OLUŞTUR
# ============================================================

def get_match_id(match):

    # API'nin verdiği gerçek maç ID'sini kullanıyoruz.
    return str(match["id"])


# ============================================================
# MAÇI TÜRKİYE SAATİNE ÇEVİR
# ============================================================

def get_match_time(match):

    utc_date = match["utcDate"]

    utc_datetime = datetime.fromisoformat(
        utc_date.replace("Z", "+00:00")
    )

    turkey_datetime = utc_datetime.astimezone(TURKEY_TZ)

    return turkey_datetime


# ============================================================
# MAÇTAN ÖNCEKİ SÜREYİ HESAPLA
# ============================================================

def get_minutes_until_match(match_datetime):

    now_utc = datetime.now(timezone.utc)

    match_utc = match_datetime.astimezone(timezone.utc)

    difference = match_utc - now_utc

    return difference.total_seconds() / 60


# ============================================================
# ANA SİSTEM
# ============================================================

def main():

    matches = get_champions_league_matches()

    if not matches:
        print("Şu anda Şampiyonlar Ligi maçı bulunamadı.")
        return

    print(f"Toplam {len(matches)} Şampiyonlar Ligi maçı bulundu.")

    matches_ready_for_prediction = []

    for match in matches:

        # Sadece planlanmış maçları dikkate al
        if match.get("status") != "SCHEDULED":
            continue

        match_id = get_match_id(match)

        # Daha önce gönderilmişse atla
        if match_id in sent_matches:
            continue

        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]

        match_datetime = get_match_time(match)

        minutes_until_match = get_minutes_until_match(
            match_datetime
        )

        print(
            f"{home_team} - {away_team} | "
            f"Türkiye saati: "
            f"{match_datetime.strftime('%d.%m.%Y %H:%M')} | "
            f"Kalan süre: "
            f"{minutes_until_match:.1f} dakika"
        )

        # Maça 1-2 saat kaldıysa seç
        if (
            MIN_MINUTES_BEFORE
            <= minutes_until_match
            <= MAX_MINUTES_BEFORE
        ):

            matches_ready_for_prediction.append({
                "id": match_id,
                "home_team": home_team,
                "away_team": away_team,
                "match_datetime": match_datetime
            })


    # ========================================================
    # ŞU ANDA TAHMİN ZAMANI GELEN MAÇ YOKSA
    # ========================================================

    if not matches_ready_for_prediction:

        print(
            "Şu anda maçtan 1-2 saat önce olan "
            "bir Şampiyonlar Ligi maçı yok."
        )

        return


    # ========================================================
    # ŞİMDİLİK TEST MESAJI
    # ========================================================

    for match in matches_ready_for_prediction:

        home_team = match["home_team"]
        away_team = match["away_team"]
        match_datetime = match["match_datetime"]
        match_id = match["id"]

        message = (
            "⚽ ŞAMPİYONLAR LİGİ TAHMİN SİSTEMİ\n\n"
            f"🏟️ {home_team} - {away_team}\n"
            f"🇹🇷 Maç saati: "
            f"{match_datetime.strftime('%d.%m.%Y %H:%M')}\n\n"
            "⏰ Maçtan 1-2 saat önce analiz zamanı geldi.\n\n"
            "🤖 AI analiz sistemi bir sonraki aşamada "
            "devreye girecek."
        )

        send_telegram_message(message)

        # Maçı gönderilmiş olarak kaydet
        sent_matches.append(match_id)


    # ========================================================
    # GÖNDERİLEN MAÇLARI KAYDET
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


# ============================================================
# PROGRAMI BAŞLAT
# ============================================================

if __name__ == "__main__":
    main()
