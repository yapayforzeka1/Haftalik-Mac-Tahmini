from __future__ import annotations
from collections import Counter, defaultdict
from typing import Any
from ai_pool import AIVote


def build_consensus(votes: list[AIVote]) -> dict[str, Any]:
    successful = [v for v in votes if v.success and v.result]
    if not successful:
        raise RuntimeError("Hiçbir AI başarılı sonuç üretmedi.")
    outcome_counts = Counter(v.result["outcome"] for v in successful)
    score_counts = Counter(v.result["score"] for v in successful)
    outcome_order = {"HOME": 0, "DRAW": 1, "AWAY": 2}
    outcome, outcome_votes = sorted(outcome_counts.items(), key=lambda x: (-x[1], outcome_order[x[0]]))[0]
    score, score_votes = score_counts.most_common(1)[0]
    reasons: dict[str, list[str]] = defaultdict(list)
    for vote in successful:
        for reason in vote.result.get("reasons", []):
            if reason not in reasons[vote.result["outcome"]]: reasons[vote.result["outcome"]].append(reason)
    failed = [{"model": v.model, "error": v.error} for v in votes if not v.success]
    avg_conf = round(sum(v.result.get("confidence", 0) for v in successful) / len(successful))
    return {
        "successful_ai": len(successful), "total_ai": len(votes),
        "outcome": outcome, "outcome_votes": outcome_votes,
        "outcome_share": round(outcome_votes / len(successful) * 100),
        "score": score, "score_votes": score_votes,
        "score_share": round(score_votes / len(successful) * 100),
        "average_subjective_confidence": avg_conf,
        "all_outcomes": dict(outcome_counts), "all_scores": dict(score_counts),
        "reasons_by_outcome": {k: v[:5] for k, v in reasons.items()},
        "disagreement": len(outcome_counts) > 1,
        "failed_ai": failed,
    }


def outcome_label(outcome: str, home: str, away: str) -> str:
    return {"HOME": home, "DRAW": "Beraberlik", "AWAY": away}[outcome]
