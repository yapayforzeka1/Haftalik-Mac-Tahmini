from __future__ import annotations

from collections import Counter
from typing import Any

from consensus_engine import outcome_label
from match_report import build_match_group_message


def build_telegram_message(record: dict[str, Any]) -> str:
    """Backward-compatible single-match wrapper for the Telegram format."""
    return build_match_group_message([record])


def build_telegram_group_message(records: list[dict[str, Any]], test_mode: bool = False) -> str:
    """Build one written Telegram message for all matches sharing a kickoff."""
    return build_match_group_message(records, test_mode=test_mode)


def _mode(record: dict[str, Any]) -> str:
    consensus = record.get("consensus") or {}
    mode = str(
        record.get("prediction_mode")
        or consensus.get("consensus_mode")
        or ""
    ).upper()

    if mode in {"NORMAL", "OUTCOME_COMMON_SCORE_SPLIT", "NO_COMMON"}:
        return mode

    winner = consensus.get("winner_consensus")
    score = consensus.get("score_consensus")
    if winner is None:
        winner = bool(consensus.get("outcome"))
    if score is None:
        score = bool(consensus.get("score"))

    if winner and score:
        return "NORMAL"
    if winner:
        return "OUTCOME_COMMON_SCORE_SPLIT"
    return "NO_COMMON"


def _outcome_text(outcome: str | None, home: str, away: str) -> str:
    return outcome_label(outcome, home, away)


def _successful_votes(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        vote
        for vote in record.get("ai_votes", [])
        if vote.get("success") and vote.get("result")
    ]


def _individual_vote_lines(record: dict[str, Any]) -> list[str]:
    home = str(record.get("home_team", "?"))
    away = str(record.get("away_team", "?"))
    lines = []
    for vote in _successful_votes(record):
        result = vote["result"]
        outcome = str(result.get("outcome", "")).upper()
        score = str(result.get("score", "?"))
        points = vote.get("points")
        point_text = "-" if points is None else f"{points}/5"
        lines.extend([
            f"• {vote.get('model', '?')}",
            f"  {_outcome_text(outcome, home, away)} | ⚽ {score} | Puan: {point_text}",
        ])
    return lines


def build_result_message(record: dict[str, Any]) -> str:
    """
    Build a result message that respects the pre-match consensus mode.

    A plurality is never presented as an "AI Ortak Kararı".
    """
    actual = record.get("actual") or {}
    if actual.get("home") is None or actual.get("away") is None:
        return ""

    home = str(record.get("home_team", "?"))
    away = str(record.get("away_team", "?"))
    actual_score = f"{actual['home']}-{actual['away']}"
    real_outcome = (
        "HOME" if actual["home"] > actual["away"]
        else "AWAY" if actual["home"] < actual["away"]
        else "DRAW"
    )
    mode = _mode(record)
    consensus = record.get("consensus") or {}

    if mode == "NORMAL":
        predicted = str(consensus.get("score") or "-").replace(" ", "")
        points = record.get("consensus_points")
        outcome_ok = consensus.get("outcome") == real_outcome
        exact_ok = predicted == actual_score

        return (
            "📊 MAÇ SONUCU\n\n"
            f"⚽ {home} - {away}\n"
            f"🏁 Gerçek skor: {actual_score}\n"
            f"🎯 AI Ortak Kararı skoru: {predicted}\n"
            f"🏆 Konsensüs puanı: {points if points is not None else '-'} / 5\n"
            f"{'✅ Maç sonucu doğru' if outcome_ok else '❌ Maç sonucu yanlış'}\n"
            f"{'✅ Tam skor tuttu' if exact_ok else '❌ Tam skor tutmadı'}"
        )

    if mode == "OUTCOME_COMMON_SCORE_SPLIT":
        outcome = consensus.get("outcome")
        votes = _successful_votes(record)
        outcome_votes = int(consensus.get("outcome_votes") or 0)
        successful = len(votes)
        points = record.get("consensus_points")
        outcome_ok = outcome == real_outcome

        lines = [
            "📊 MAÇ SONUCU",
            "",
            f"⚽ {home} - {away}",
            f"🏁 Gerçek skor: {actual_score}",
            "",
            "🟢 ORTAK KAZANAN VAR",
            f"🏆 {_outcome_text(outcome, home, away)} — {outcome_votes}/{successful} AI",
            f"{'✅ Ortak sonuç doğru' if outcome_ok else '❌ Ortak sonuç yanlış'}",
            f"🏆 Ortak kazanan puanı: {points if points is not None else '-'} / 5",
            "",
            "🟡 SKORDA ORTAK KARAR YOK",
            "",
            "🎯 AI BİREYSEL TAHMİNLERİ",
        ]
        lines.extend(_individual_vote_lines(record))
        return "\n".join(lines)

    # NO_COMMON
    votes = _successful_votes(record)
    outcome_counts = Counter(str(v["result"].get("outcome", "")).upper() for v in votes)
    score_counts = Counter(
        str(v["result"].get("score", "")).replace(" ", "")
        for v in votes
    )

    lines = [
        "📊 MAÇ SONUCU",
        "",
        f"⚽ {home} - {away}",
        f"🏁 Gerçek skor: {actual_score}",
        "",
        "🔴 ORTAK KARAR YOK",
        "",
        "🏆 Kazanan tahminleri:",
        f"• {home}: {outcome_counts.get('HOME', 0)} AI",
        f"• Beraberlik: {outcome_counts.get('DRAW', 0)} AI",
        f"• {away}: {outcome_counts.get('AWAY', 0)} AI",
        "",
        "🎯 Skor tahminleri:",
    ]

    if score_counts:
        for score, count in score_counts.most_common():
            lines.append(f"• {score}: {count} AI")
    else:
        lines.append("• Veri yok")

    lines.extend([
        "",
        "🤖 BİREYSEL AI DEĞERLENDİRMESİ",
    ])
    lines.extend(_individual_vote_lines(record))
    lines.extend([
        "",
        "📌 Bu maç için konsensüs puanı uygulanmadı.",
        "📊 Bireysel AI tahminleri ayrı olarak değerlendirildi.",
    ])
    return "\n".join(lines)
