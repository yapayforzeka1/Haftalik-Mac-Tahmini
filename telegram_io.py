"""Telegram transport with redacted errors and durable per-part delivery."""
import requests


class TelegramError(RuntimeError):
    """A Telegram operation failed."""


class TelegramDeliveryUncertain(TelegramError):
    """The request may have reached Telegram, but no reliable response arrived."""


class Telegram:
    def __init__(self, token):
        self.token = token

    def call(self, method, **payload):
        try:
            response = requests.post(f"https://api.telegram.org/bot{self.token}/{method}",
                                     json=payload, timeout=20)
        except requests.RequestException:
            error = "Telegram bağlantısı başarısız; token gizlendi."
            if method == "sendMessage":
                raise TelegramDeliveryUncertain(error) from None
            raise TelegramError(error) from None
        if response.status_code >= 500:
            error = f"Telegram işlem hatası ({response.status_code})."
            if method == "sendMessage":
                raise TelegramDeliveryUncertain(error)
            raise TelegramError(error)
        try:
            data = response.json()
        except ValueError:
            error = "Telegram yanıtı okunamadı; token gizlendi."
            if method == "sendMessage" and response.ok:
                raise TelegramDeliveryUncertain(error) from None
            raise TelegramError(error) from None
        if not isinstance(data, dict):
            error = f"Telegram işlem hatası ({response.status_code})."
            if method == "sendMessage" and response.ok:
                raise TelegramDeliveryUncertain(error)
            raise TelegramError(error)
        if not response.ok:
            raise TelegramError(f"Telegram işlem hatası ({response.status_code}).")
        if data.get("ok") is False:
            raise TelegramError(f"Telegram işlem hatası ({response.status_code}).")
        if data.get("ok") is not True:
            error = f"Telegram işlem yanıtı belirsiz ({response.status_code})."
            if method == "sendMessage":
                raise TelegramDeliveryUncertain(error)
            raise TelegramError(error)
        return data.get("result")

    def photo(self, chat_id, path):
        try:
            with path.open("rb") as file:
                response = requests.post(f"https://api.telegram.org/bot{self.token}/sendPhoto",
                    data={"chat_id": chat_id}, files={"photo": file}, timeout=30)
        except requests.RequestException:
            raise TelegramDeliveryUncertain(
                "Telegram görsel bağlantısı belirsiz; otomatik tekrar engellendi.") from None
        if response.status_code >= 500:
            raise TelegramDeliveryUncertain(
                f"Telegram görsel yanıtı belirsiz ({response.status_code}); otomatik tekrar engellendi.")
        try:
            data = response.json()
        except ValueError:
            if response.ok:
                raise TelegramDeliveryUncertain(
                    "Telegram görsel yanıtı okunamadı; otomatik tekrar engellendi.") from None
            raise TelegramError("Telegram görsel gönderimi başarısız.") from None
        if not isinstance(data, dict):
            if response.ok:
                raise TelegramDeliveryUncertain(
                    "Telegram görsel yanıtı beklenen biçimde değil; otomatik tekrar engellendi.")
            raise TelegramError("Telegram görsel gönderimi başarısız.")
        if not response.ok or data.get("ok") is False:
            raise TelegramError("Telegram görsel gönderimi başarısız.")
        if data.get("ok") is not True:
            raise TelegramDeliveryUncertain(
                "Telegram görsel yanıtı belirsiz; otomatik tekrar engellendi.")
        return data.get("result")


def chunks(text, limit=1800):
    # 1800 code points leaves room even when every character is a UTF-16 pair.
    return [text[i:i+limit] for i in range(0, len(text), limit)]


def deliver_text(bot, chat_id, text, receipt, save):
    if receipt.get("uncertain"):
        raise TelegramDeliveryUncertain(
            "Telegram metin gönderimi sonucu belirsiz; tekrar gönderim engellendi.")
    parts = chunks(text)
    for i in range(receipt.get("parts_sent", 0), len(parts)):
        try:
            result = bot.call("sendMessage", chat_id=chat_id, text=parts[i])
        except TelegramDeliveryUncertain:
            receipt["uncertain"] = True
            receipt["uncertain_part"] = i + 1
            save()
            raise
        receipt["parts_sent"] = i + 1
        receipt.setdefault("message_ids", []).append(result["message_id"])
        save()
    receipt["complete"] = True
    save()
