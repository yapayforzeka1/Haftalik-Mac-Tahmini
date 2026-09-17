"""Private approval inbox. Polling is periodic, not an always-on webhook."""
from datetime import datetime, timedelta, timezone

from learning import POLICIES, digest, utcnow
from telegram_io import TelegramError, deliver_text


def proposal_text(p, details=False):
    e = p["evidence"]
    text = (f"🔧 Geliştirme önerisi #{p['id']}\n\n"
            f"Tespit: {p['reason']}\n"
            f"Değişiklik: {p['previous_policy']} → {p['policy']}\n"
            f"Yeni talimat: {p['instruction']}\n\n"
            f"Kanıt: {e.get('group_a', 'XI var')} {e['with_xi_matches']} maç, en az bir AI tam isabet oranı "
            f"%{100*e['with_xi_any_exact_rate']:.1f}; {e.get('group_b', 'XI yok')} {e['without_xi_matches']} maç, "
            f"%{100*e['without_xi_any_exact_rate']:.1f}.\n"
            f"Sınırlama: {e['limitation']}\n\n"
            "Puanlama ve çoğunluk kuralı değişmez. Onay yalnızca sonraki tahminleri etkiler.\n"
            "Karar sonraki bot çalışmasında işlenir; ayrıca bildirilir. Öneri 7 gün geçerlidir.")
    if details:
        text += "\n\nMaç kimlikleri: " + ", ".join(e["match_ids"])
        text += "\nÖlçüm: maç başına en az bir modelin tam skor isabeti; nedensel deney değildir."
    return text


def fingerprint(p):
    return digest({k: p[k] for k in ("id", "base_revision", "policy", "instruction", "evidence")})[:12]


def handle_callback(query, state, admin_id, chat_id, now=None):
    now = now or datetime.now(timezone.utc)
    message = query.get("message") or {}
    if (str(query.get("from", {}).get("id")) != str(admin_id)
            or str(message.get("chat", {}).get("id")) != str(chat_id)
            or message.get("chat", {}).get("type") != "private"):
        return "Yetkisiz işlem."
    parts = str(query.get("data", "")).split(":")
    if len(parts) != 3 or parts[0] not in {"approve", "reject", "detail"}:
        return "Geçersiz işlem."
    action, pid, stamp = parts
    p = state["proposals"].get(pid)
    if not p or stamp != fingerprint(p) or message.get("message_id") != p.get("message_id"):
        return "Öneri doğrulanamadı."
    if action == "detail":
        return proposal_text(p, details=True)
    if p["status"] != "PENDING":
        return f"Bu öneri daha önce işlendi: {p['status']}."
    if (now - datetime.fromisoformat(p["created_at"]) > timedelta(days=7)
            or p["base_revision"] != state["revision"]):
        p["status"] = "STALE"
        return "Öneri süresi dolmuş veya ayarlar değişmiş; uygulanmadı."
    if action == "approve":
        if p["policy"] not in POLICIES or p["instruction"] != POLICIES[p["policy"]]:
            return "İzin verilen ayarlarla uyuşmuyor; uygulanmadı."
        state["policy"] = p["policy"]
        state["revision"] += 1
        p["status"] = "APPROVED"
    else:
        p["status"] = "REJECTED"
    p["decided_at"] = now.isoformat()
    state["decisions"].append({"proposal": pid, "action": action, "actor": "configured_admin",
        "at": p["decided_at"], "previous": p["previous_policy"], "current": state["policy"],
        "revision": state["revision"]})
    return (f"✅ #{pid} onayı kaydedildi; {state['policy']} sonraki tahminlerde uygulanacak."
            if action == "approve" else f"❌ #{pid} reddedildi; ayarlar değiştirilmedi.")


def run_operations(bot, state, save, admin_id, chat_id):
    if not admin_id or not chat_id:
        raise ValueError("Operasyon chat/admin secret'ları eksik.")
    state['notices'].setdefault('welcome', {'text':
        '✅ Şampiyonlar Ligi AI Operasyon hazır.\n'
        'Geliştirme önerileri Onayla / Reddet / Ayrıntı düğmeleriyle iletilecek. '
        'Kararlar sonraki GitHub Actions çalışmasında işlenir. '
        'Yeterli kanıt yoksa öneri üretilmez; onaysız ayar değişmez.', 'receipt': {}})
    updates = bot.call("getUpdates", offset=state["update_offset"], timeout=0,
                       allowed_updates=["callback_query", "message"])
    for update in updates or []:
        uid = update["update_id"]
        if uid < state["update_offset"]:
            continue
        query = update.get("callback_query")
        if query:
            reply = handle_callback(query, state, admin_id, chat_id)
            authorized = (str(query.get("from", {}).get("id")) == str(admin_id)
                          and str(query.get("message", {}).get("chat", {}).get("id")) == str(chat_id))
            if authorized:
                state["notices"][str(uid)] = {"text": reply, "receipt": {}}
            # Save the decision and cursor together BEFORE acknowledging externally.
            state["update_offset"] = uid + 1
            save()
            try:
                bot.call("answerCallbackQuery", callback_query_id=query["id"], text="Karar işlendi.")
            except TelegramError:
                # Callback may have expired while Actions was idle; decision is still durable.
                pass
        else:
            state["update_offset"] = uid + 1
            save()
    for notice in state["notices"].values():
        if not notice["receipt"].get("complete"):
            deliver_text(bot, chat_id, notice["text"], notice["receipt"], save)
    for p in state["proposals"].values():
        if p["status"] != "PENDING":
            if p.get("message_id") and not p.get("buttons_removed"):
                try:
                    bot.call("editMessageReplyMarkup", chat_id=chat_id,
                             message_id=p["message_id"], reply_markup={"inline_keyboard": []})
                    p["buttons_removed"] = True
                    save()
                except TelegramError:
                    pass
            continue
        if p.get("notified"):
            continue
        stamp = fingerprint(p)
        buttons = [[{"text": label, "callback_data": f"{action}:{p['id']}:{stamp}"}
                    for label, action in [("✅ Onayla", "approve"), ("❌ Reddet", "reject"), ("📋 Ayrıntı", "detail")]]]
        result = bot.call("sendMessage", chat_id=chat_id, text=proposal_text(p),
                          reply_markup={"inline_keyboard": buttons})
        p.update(notified=True, message_id=result["message_id"])
        save()
