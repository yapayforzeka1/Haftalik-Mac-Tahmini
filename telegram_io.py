"""Telegram transport with redacted errors and durable per-part delivery."""
import requests


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, token):
        self.token = token

    def call(self, method, **payload):
        try:
            response = requests.post(f"https://api.telegram.org/bot{self.token}/{method}",
                                     json=payload, timeout=20)
            data = response.json()
        except (requests.RequestException, ValueError):
            raise TelegramError("Telegram bağlantısı başarısız; token gizlendi.") from None
        if not response.ok or not data.get("ok"):
            raise TelegramError(f"Telegram işlem hatası ({response.status_code}).")
        return data.get("result")

    def photo(self, chat_id, path):
        try:
            with path.open("rb") as file:
                response = requests.post(f"https://api.telegram.org/bot{self.token}/sendPhoto",
                    data={"chat_id": chat_id}, files={"photo": file}, timeout=30)
            if not response.ok or not response.json().get("ok"):
                raise TelegramError("Telegram görsel gönderimi başarısız.")
        except (requests.RequestException, ValueError):
            raise TelegramError("Telegram görsel bağlantısı başarısız; token gizlendi.") from None


def chunks(text, limit=1800):
    # 1800 code points leaves room even when every character is a UTF-16 pair.
    return [text[i:i+limit] for i in range(0, len(text), limit)]


def deliver_text(bot, chat_id, text, receipt, save):
    parts = chunks(text)
    for i in range(receipt.get("parts_sent", 0), len(parts)):
        result = bot.call("sendMessage", chat_id=chat_id, text=parts[i])
        receipt["parts_sent"] = i + 1
        receipt.setdefault("message_ids", []).append(result["message_id"])
        save()
    receipt["complete"] = True
    save()
