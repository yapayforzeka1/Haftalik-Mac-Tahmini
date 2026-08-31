import os
import requests
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
FOOTBALL_DATA_API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]

# Football-data.org API
url = "https://api.football-data.org/v4/competitions/CL/matches"

headers = {
    "X-Auth-Token": FOOTBALL_DATA_API_KEY
}

response = requests.get(url, headers=headers)
response.raise_for_status()

data = response.json()

matches = data.get("matches", [])

# Şampiyonlar Ligi maçlarını hazırla
if not matches:
    message = "⚽ Şu anda listelenmiş Şampiyonlar Ligi maçı bulunamadı."
else:
    lines = ["⚽ ŞAMPİYONLAR LİGİ MAÇLARI\n"]

    for match in matches[:10]:
        home = match["homeTeam"]["name"]
        away = match["awayTeam"]["name"]

        utc_date = match["utcDate"]
        date = datetime.fromisoformat(
            utc_date.replace("Z", "+00:00")
        )

        lines.append(
            f"🏟️ {home} - {away}\n"
            f"📅 {date.strftime('%d.%m.%Y %H:%M')} UTC\n"
        )

    message = "\n".join(lines)

# Telegram'a gönder
telegram_url = (
    f"https://api.telegram.org/bot"
    f"{TELEGRAM_BOT_TOKEN}/sendMessage"
)

requests.post(
    telegram_url,
    data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
)

print(message)
