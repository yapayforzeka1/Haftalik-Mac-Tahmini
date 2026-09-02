from __future__ import annotations

from typing import Any

from consensus_engine import outcome_label
from match_report import build_match_group_message


def build_telegram_message(record: dict[str, Any]) -> str:
    """Backward-compatible single-match wrapper for the new Telegram format."""
    return build_match_group_message([record])


def build_telegram_group_message(records: list[dict[str, Any]], test_mode: bool = False) -> str:
    """Build one written Telegram message for all matches sharing a kickoff."""
    return build_match_group_message(records, test_mode=test_mode)


def build_result_message(record: dict[str, Any]) -> str:
    """Build the compact post-match result message."""
    actual = record.get("actual") or {}
    if actual.get("home") is None or actual.get("away") is None:
        return ""

    consensus = record["consensus"]
    predicted = str(consensus.get("score", "")).replace(" ", "")
    actual_score = f"{actual['home']}-{actual['away']}"
    actual_outcome = "HOME" if actual["home"] > actual["away"] else "AWAY" if actual["home"] < actual["away"] else "DRAW"
    points = record.get("consensus_points")

    return (
        "📊 MAÇ SONUCU\n\n"
        f"⚽ {record['home_team']} - {record['away_team']}\n"
        f"🏁 Gerçek skor: {actual_score}\n"
        f"🎯 AI Ortak Kararı skoru: {predicted}\n"
        f"🏆 Konsensüs puanı: {points if points is not None else '-'} / 5\n"
        f"{'✅ Maç sonucu doğru' if consensus.get('outcome') == actual_outcome else '❌ Maç sonucu yanlış'}\n"
        f"{'✅ Tam skor tuttu' if predicted == actual_score else '❌ Tam skor tutmadı'}"
    )
