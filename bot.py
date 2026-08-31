import os
import requests
from openai import OpenAI

# GitHub Secrets
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# OpenAI bağlantısı
client = OpenAI(api_key=OPENAI_API_KEY)

# AI'ya test sorusu
response = client.responses.create(
    model="gpt-5",
    input="Şampiyonlar Ligi nedir? Tek cümleyle cevap ver."
)

answer = response.output_text

# Telegram'a gönder
telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

requests.post(
    telegram_url,
    data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "🤖 AI TEST\n\n" + answer
    }
)

print(answer)
