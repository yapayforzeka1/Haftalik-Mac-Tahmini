import os
import requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

message = "🤖 Şampiyonlar Ligi Tahmin Botu çalışıyor!\n\nTelegram bağlantısı başarıyla kuruldu. ⚽"

response = requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    }
)

print(response.json())
