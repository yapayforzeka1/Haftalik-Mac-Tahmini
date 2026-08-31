import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
FOOTBALL_DATA_API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]

# Türkiye saat dilimi
TURKEY_TZ = ZoneInfo("Europe/Istanbul")

# Football-data.org API
url = "https://api.football-data.org/v4/competitions/CL/matches"

headers = {
    "X-Auth-Token": FOOTBALL_DATA_API_KEY
}

response = requests.get(url, headers=headers)
response.raise_for_status()

data = response.json()
matches = data.get("matches", [])

if not matches:
    message = "⚽ Şu anda listelenmiş Şampiyonlar Ligi maçı bulunamadı."

else:
    lines = ["⚽ ŞAMPİYONLAR LİGİ MAÇLARI\n"]

    for match in matches[:10]:
        home = match["homeTeam"]["name"]
        away = match["awayTeam"]["name"]

        # API'den gelen UTC zamanı al
        utc_date = match["utcDate"]

        utc_datetime = datetime.fromisoformat(
            utc_date.replace("Z", "+00:00")
        )

        # Türkiye saatine çevir
        turkey_datetime = utc_datetime.astimezone(TURKEY_TZ)

        lines.append(
            f"🏟️ {home} - {away}\n"
            f"🇹🇷 Maç saati: "
            f"{turkey_datetime.strftime('%d.%m.%Y %H:%M')}\n"
        )

    message = "\n".join(lines)

# Telegram'a gönder
telegram_url = (
    f"https://api.telegram.org/bot"
    f"{TELEGRAM_BOT_TOKEN}/sendMessage"
)

telegram_response = requests.post(
    telegram_url,
    data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
)

telegram_response.raise_for_status()

print(message)
