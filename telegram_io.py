"""Telegram transport with redacted errors and durable per-part delivery."""
import requests


class TelegramError(RuntimeError):
    """A Telegram operation failed."""

    def __init__(self, message, *, reason='UNKNOWN', http_status=None, retry_after=None):
        super().__init__(message)
        allowed = {'UNKNOWN', 'CONNECT_TIMEOUT', 'READ_TIMEOUT', 'TIMEOUT',
                   'CONNECTION_ERROR', 'REQUEST_ERROR', 'SERVER_ERROR', 'INVALID_JSON',
                   'INVALID_RESPONSE', 'HTTP_ERROR', 'API_REJECTED', 'MISSING_OK',
                   'MISSING_MESSAGE_ID'}
        self.reason = reason if reason in allowed else 'UNKNOWN'
        self.http_status = (http_status if type(http_status) is int and
                            100 <= http_status <= 599 else None)
        self.retry_after = retry_after if type(retry_after) is int and retry_after >= 0 else None


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

    def photo(self, chat_id, path, caption=None):
        payload = {"chat_id": chat_id}
        if caption:
            payload["caption"] = str(caption)[:1000]
        try:
            with path.open("rb") as file:
                response = requests.post(f"https://api.telegram.org/bot{self.token}/sendPhoto",
                    data=payload, files={"photo": file}, timeout=(10, 60))
        except requests.RequestException as exc:
            reason = ('CONNECT_TIMEOUT' if isinstance(exc, requests.ConnectTimeout) else
                      'READ_TIMEOUT' if isinstance(exc, requests.ReadTimeout) else
                      'TIMEOUT' if isinstance(exc, requests.Timeout) else
                      'CONNECTION_ERROR' if isinstance(exc, requests.ConnectionError) else
                      'REQUEST_ERROR')
            raise TelegramDeliveryUncertain(
                "Telegram görsel bağlantısı belirsiz; teslimat doğrulanamadı.",
                reason=reason) from None
        if response.status_code >= 500:
            raise TelegramDeliveryUncertain(
                "Telegram görsel sunucu yanıtı belirsiz; teslimat doğrulanamadı.",
                reason='SERVER_ERROR', http_status=response.status_code)
        try:
            data = response.json()
        except ValueError:
            if response.ok:
                raise TelegramDeliveryUncertain(
                    "Telegram görsel yanıtı okunamadı; teslimat doğrulanamadı.",
                    reason='INVALID_JSON', http_status=response.status_code) from None
            raise TelegramError("Telegram görsel gönderimi başarısız.",
                                reason='HTTP_ERROR', http_status=response.status_code) from None
        if not isinstance(data, dict):
            if response.ok:
                raise TelegramDeliveryUncertain(
                    "Telegram görsel yanıtı beklenen biçimde değil; teslimat doğrulanamadı.",
                    reason='INVALID_RESPONSE', http_status=response.status_code)
            raise TelegramError("Telegram görsel gönderimi başarısız.",
                                reason='HTTP_ERROR', http_status=response.status_code)
        if not response.ok or data.get("ok") is False:
            parameters = data.get('parameters')
            retry_after = parameters.get('retry_after') if isinstance(parameters, dict) else None
            raise TelegramError("Telegram görsel gönderimi başarısız.", reason='API_REJECTED',
                                http_status=response.status_code, retry_after=retry_after)
        if data.get("ok") is not True:
            raise TelegramDeliveryUncertain(
                "Telegram görsel yanıtı belirsiz; teslimat doğrulanamadı.",
                reason='MISSING_OK', http_status=response.status_code)
        result = data.get('result')
        if (not isinstance(result, dict) or type(result.get('message_id')) is not int
                or result['message_id'] <= 0):
            raise TelegramDeliveryUncertain(
                "Telegram görsel mesaj kimliği eksik; teslimat doğrulanamadı.",
                reason='MISSING_MESSAGE_ID', http_status=response.status_code)
        print(f'TELEGRAM PHOTO | status=SENT | message_id={result["message_id"]} | HTTP={response.status_code}', flush=True)
        return result


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
