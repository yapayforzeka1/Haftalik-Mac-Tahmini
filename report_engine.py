from __future__ import annotations
from typing import Any
from consensus_engine import outcome_label


def build_telegram_message(record: dict[str, Any]) -> str:
    home, away, c = record["home_team"], record["away_team"], record["consensus"]
    research = record.get("research", {})
    votes = record.get("ai_votes", [])
    lines = ["🏆 HAFTALIK MAÇ ANALİZİ", "", f"⚽ {home} - {away}", f"🇹🇷 Maç saati: {record['match_time']}", "",
        "🤖 AI KONSENSÜSÜ", f"Sonuç: {outcome_label(c['outcome'], home, away)} — {c['outcome_share']}% ({c['outcome_votes']}/{c['successful_ai']} AI)",
        f"Skor: {c['score']} — {c['score_share']}% ({c['score_votes']}/{c['successful_ai']} AI)",
        f"AI öznel güven ort.: {c['average_subjective_confidence']}/100", ""]
    if c.get("disagreement"): lines += ["⚠️ AI'lar sonuçta farklı düşünüyor.", ""]
    for v in votes:
        if v["success"]:
            r = v["result"]; lines.append(f"• {v['model']}: {outcome_label(r['outcome'], home, away)} / {r['score']}")
        else: lines.append(f"• {v['model']}: ⚠️ başarısız")
    summary = research.get("summary")
    if summary: lines += ["", "🔎 ARAŞTIRMA ÖZETİ", summary[:800]]
    reasons = c.get("reasons_by_outcome", {}).get(c["outcome"], [])
    if reasons: lines += ["", "📌 KONSENSÜS NEDENLERİ"] + [f"• {x}" for x in reasons[:3]]
    conflicts = research.get("conflicts", [])
    if conflicts: lines += ["", "⚠️ VERİ ÇELİŞKİLERİ"] + [f"• {x}" for x in conflicts[:2]]
    if research.get("status") == "UNAVAILABLE": lines += ["", "⚠️ Güncel web araştırması alınamadı; tahmin mevcut yapılandırılmış verilerle üretildi."]
    if research.get("research_confidence"): lines += ["", f"📚 Araştırma güveni: {research['research_confidence']}"]
    return "\n".join(lines)


def build_result_message(record: dict[str, Any]) -> str:
    actual = record.get("actual") or {}
    if actual.get("home") is None or actual.get("away") is None: return ""
    c = record["consensus"]; predicted = c["score"].replace(" ", ""); actual_score = f"{actual['home']}-{actual['away']}"
    actual_outcome = "HOME" if actual["home"] > actual["away"] else "AWAY" if actual["home"] < actual["away"] else "DRAW"
    return ("📊 MAÇ SONUCU\n\n" f"⚽ {record['home_team']} - {record['away_team']}\n" f"🏁 Gerçek skor: {actual_score}\n"
        f"🎯 AI konsensüs skoru: {predicted}\n" f"{'✅ Tam skor tuttu' if predicted == actual_score else '❌ Tam skor tutmadı'}\n"
        f"{'✅ Maç sonucu doğru' if c['outcome'] == actual_outcome else '❌ Maç sonucu yanlış'}")
