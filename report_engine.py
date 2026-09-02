from __future__ import annotations

from typing import Any

from consensus_engine import outcome_label


def build_telegram_message(record: dict[str, Any]) -> str:
    """Build the short, user-facing weekly prediction message for Telegram."""
    home = record["home_team"]
    away = record["away_team"]
    consensus = record["consensus"]

    successful_ai = int(consensus.get("successful_ai") or 0)
    outcome_votes = int(consensus.get("outcome_votes") or 0)
    score_votes = int(consensus.get("score_votes") or 0)

    outcome_share = int(consensus.get("outcome_share") or 0)
    score_share = int(consensus.get("score_share") or 0)

    outcome = outcome_label(consensus["outcome"], home, away)
    score = str(consensus.get("score") or "-")

    # Güven oranı = kazanan tahminindeki AI konsensüs oranı.
    confidence = outcome_share

    lines = [
        "🏆 ŞAMPİYONLAR LİGİ — HAFTALIK TAHMİN",
        "",
        f"Maç : {home} - {away}",
        f"Kim Kazanır : {outcome} — %{outcome_share} ({outcome_votes}/{successful_ai})",
        f"Skor : {score} — %{score_share} ({score_votes}/{successful_ai})",
        f"Güven oranı : %{confidence}",
    ]

    return "\n".join(lines)


def build_result_message(record: dict[str, Any]) -> str:
    """Build the post-match result message kept for the existing workflow."""
    actual = record.get("actual") or {}

    if actual.get("home") is None or actual.get("away") is None:
        return ""

    consensus = record["consensus"]

    predicted = str(
        consensus.get("score", "")
    ).replace(" ", "")

    actual_score = f"{actual['home']}-{actual['away']}"
    exact = predicted == actual_score

    predicted_outcome = consensus["outcome"]

    actual_outcome = (
        "HOME"
        if actual["home"] > actual["away"]
        else "AWAY"
        if actual["home"] < actual["away"]
        else "DRAW"
    )

    return (
        "📊 MAÇ SONUCU\n\n"
        f"⚽ {record['home_team']} - {record['away_team']}\n"
        f"🏁 Gerçek skor: {actual_score}\n"
        f"🎯 AI konsensüs skoru: {predicted}\n"
        f"{'✅ Tam skor tuttu' if exact else '❌ Tam skor tutmadı'}\n"
        f"{'✅ Maç sonucu doğru' if predicted_outcome == actual_outcome else '❌ Maç sonucu yanlış'}"
    )
