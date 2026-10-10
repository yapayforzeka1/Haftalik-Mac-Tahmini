from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from ai_pool import AIVote


CONSENSUS_MODES = {
    "NORMAL",
    "OUTCOME_COMMON_SCORE_SPLIT",
    "NO_COMMON",
}


def _strict_majority(counts: Counter[str], total: int) -> tuple[str | None, int]:
    """Return a unique strict-majority value; ties/pluralities are not consensus."""
    if total <= 0 or not counts:
        return None, 0
    value, count = counts.most_common(1)[0]
    top_count = sum(1 for item in counts.values() if item == count)
    if top_count != 1 or count < 3:
        return None, 0
    return value, count


def classify_consensus_mode(outcome_counts: Counter[str], score_counts: Counter[str], successful_count: int, min_successful: int = 3) -> str:
    if successful_count < max(3, min_successful):
        return "NO_COMMON"

    outcome, _ = _strict_majority(outcome_counts, successful_count)
    if outcome is None:
        return "NO_COMMON"

    score, _ = _strict_majority(score_counts, successful_count)
    if score is None:
        return "OUTCOME_COMMON_SCORE_SPLIT"

    return "NORMAL"


def build_consensus(votes: list[AIVote], min_successful: int = 3) -> dict[str, Any]:
    """
    Consensus is deliberately stricter than a simple plurality.

    - Winner/outcome consensus requires at least 3 identical votes.
    - Exact-score consensus requires at least 3 identical consistent votes.
    - If the winner has consensus but the score does not, score is NOT promoted
      to consensus; it remains only as top_score/top_score_votes for information.
    - If there is no winner consensus, outcome and score are both left unset.
    """
    min_successful = max(3, min_successful)
    successful = [v for v in votes if v.success and v.result]
    if not successful:
        raise RuntimeError("Hiçbir AI başarılı sonuç üretmedi.")

    outcome_counts = Counter(str(v.result.get("outcome", "")).upper() for v in successful)
    score_counts = Counter(str(v.result.get("score", "")).replace(" ", "") for v in successful)

    outcome, outcome_votes = _strict_majority(outcome_counts, len(successful))
    winning_scores = Counter(str(v.result.get("score", "")).replace(" ", "") for v in successful if v.result.get("outcome") == outcome) if outcome else Counter()
    score, score_votes = _strict_majority(winning_scores, len(successful))

    mode = classify_consensus_mode(outcome_counts, score_counts, len(successful), min_successful)

    if mode == "NO_COMMON":
        outcome = None
        outcome_votes = 0
        score = None
        score_votes = 0
    elif mode == "OUTCOME_COMMON_SCORE_SPLIT":
        # The common outcome is valid, but no exact score is a consensus.
        score = None
        score_votes = 0

    top_outcome, top_outcome_votes = outcome_counts.most_common(1)[0]
    top_score, top_score_votes = score_counts.most_common(1)[0]

    reasons: dict[str, list[str]] = defaultdict(list)
    for vote in successful:
        result = vote.result or {}
        for reason in result.get("reasons", []):
            outcome_key = str(result.get("outcome", "")).upper()
            if reason not in reasons[outcome_key]:
                reasons[outcome_key].append(reason)

    failed = [{"model": v.model, "error": v.error} for v in votes if not v.success]
    avg_conf = round(
        sum(int(v.result.get("confidence", 0) or 0) for v in successful) / len(successful)
    )

    return {
        "min_successful": min_successful,
        "successful_ai": len(successful),
        "total_ai": len(votes),

        # Only true consensus values go into these legacy-facing fields.
        "outcome": outcome,
        "outcome_votes": outcome_votes,
        "outcome_share": round(outcome_votes / len(successful) * 100) if outcome_votes else 0,
        "score": score,
        "score_votes": score_votes,
        "score_share": round(score_votes / len(successful) * 100) if score_votes else 0,

        # Explicit flags make downstream grading/reporting unambiguous.
        "winner_consensus": outcome is not None,
        "score_consensus": score is not None,
        "consensus_mode": mode,

        # Informational plurality values. These are NEVER treated as consensus.
        "top_outcome": top_outcome,
        "top_outcome_votes": top_outcome_votes,
        "top_score": top_score,
        "top_score_votes": top_score_votes,

        "average_subjective_confidence": avg_conf,
        "all_outcomes": dict(outcome_counts),
        "all_scores": dict(score_counts),
        "reasons_by_outcome": {k: v[:5] for k, v in reasons.items()},
        "disagreement": len(outcome_counts) > 1,
        "failed_ai": failed,
    }


def outcome_label(outcome: str | None, home: str, away: str) -> str:
    if outcome == "HOME":
        return home
    if outcome == "AWAY":
        return away
    if outcome == "DRAW":
        return "Beraberlik"
    return "Ortak karar yok"
