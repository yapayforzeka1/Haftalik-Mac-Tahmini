import os
import requests
from google import genai

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Gemini bağlantısı
client = genai.Client(api_key=GEMINI_API_KEY)

# Basit test
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Şampiyonlar Ligi nedir? Tek cümleyle cevap ver."
)

answer = response.text

# Telegram'a gönder
telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

requests.post(
    telegram_url,
    data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "🤖 GEMINI TEST\n\n" + answer
    }
)

print(answer)
