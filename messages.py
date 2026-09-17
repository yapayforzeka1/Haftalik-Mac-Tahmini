"""All prediction modes use the same plain-text vocabulary and denominator."""
from collections import Counter


def label(value, record):
    return {"HOME": record["home_team"], "AWAY": record["away_team"], "DRAW": "Beraberlik"}.get(value, "—")


def prediction_message(record):
    lines = [f"⚽ {record['home_team']} — {record['away_team']} | 🕒 TSİ: {record['match_time']}"]
    kind = record.get("prediction_kind", "AI")
    if kind == "UNAVAILABLE":
        return "\n".join(lines + ["⚠️ Yeterli veri olmadığı için tahmin üretilemedi."])
    if kind == "STATISTICAL":
        return "\n".join(lines + ["📐 İstatistiksel yedek tahmin — AI servislerinden yanıt alınamadı.",
            f"🎯 Skor: {record['fallback']['score']}", "AI konsensüsü değildir; ayrı değerlendirilir."])
    votes = [v for v in record.get("ai_votes", []) if v.get("success") and v.get("result")]
    c = record.get("consensus") or {}
    n = len(votes)
    mode = c.get("consensus_mode", "NO_COMMON")
    if mode == "NORMAL":
        lines += [f"🤖 AI Ortak Kararı: {label(c['outcome'], record)} — Uzlaşma %{c['outcome_share']} ({c['outcome_votes']}/{n})",
                  f"🎯 Skor: {c['score']} — Uzlaşma %{c['score_share']} ({c['score_votes']}/{n})",
                  f"📊 AI Güveni: %{c.get('average_subjective_confidence', 0)} — öznel güven"]
    else:
        lines += ["🟡 SONUÇ ORTAK — SKOR AYRIŞTI" if mode == "OUTCOME_COMMON_SCORE_SPLIT" else "🔴 SONUÇ VE SKOR AYRIŞMA"]
        if mode == "OUTCOME_COMMON_SCORE_SPLIT":
            lines += [f"🎯 Ortak AI Sonucu: {label(c['outcome'], record)} ({c['outcome_votes']}/{n})"]
        else:
            lines += ["Ortak karar yok." if n != 1 else "Yalnızca bir AI yanıtladı; bireysel tahmin."]
        lines += ["\n🤖 Bireysel Skor Tahminleri"]
        for vote in votes:
            r = vote["result"]
            reasons = r.get("reasons") or ["Gerekçe belirtilmedi."]
            reason = str(reasons[0]).replace("\n", " ")[:220]
            lines += [f"• {vote['model']}: {label(r['outcome'], record)} — {r['score']} | {reason}"]
        if mode == "NO_COMMON":
            lines += ["\nSonuç Dağılımı:"]
            for value, count in Counter(v["result"]["outcome"] for v in votes).most_common():
                lines += [f"{label(value, record)}: ({count}/{n})"]
        lines += ["\nSkor Dağılımı:"]
        for value, count in Counter(v["result"]["score"] for v in votes).most_common():
            lines += [f"{value}: ({count}/{n})"]
    xi = (record.get("context") or {}).get("official_xi") or {}
    if xi.get("status") == "ANNOUNCED":
        lines += [f"✅ Resmî XI teyitli — {xi.get('source', 'veri sağlayıcı')}"]
    else:
        predicted = (record.get("context") or {}).get("predicted_xi") or {}
        complete = all(len(predicted.get(side, [])) == 11 for side in ("home", "away"))
        lines += ["⚠️ Resmî XI teyit edilemedi; tahmini kadro kullanıldı." if complete
                  else "⚠️ Resmî XI teyit edilemedi; kadro bilgisi eksik, mevcut veriler kullanıldı."]
    lines += ["ℹ️ Skorlar ev sahibi–deplasman sırasındadır. Uzlaşma, gerçekleşme olasılığı değildir.",
              "Kapsam: 90 dakika + hakem ek süresi."]
    return "\n".join(lines)
