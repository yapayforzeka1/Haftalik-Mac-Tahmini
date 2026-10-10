from __future__ import annotations

from collections import Counter
from typing import Any

from consensus_engine import AIVote, build_consensus


def _same_team(record: dict[str, Any], team: str) -> bool:
    return record.get("home_team") == team or record.get("away_team") == team


def actual_outcome(home: int, away: int) -> str:
    return "HOME" if home > away else "AWAY" if home < away else "DRAW"


from scoring import VERSION, outcome_points, score_prediction


def _rebuild_consensus_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Recompute consensus from the archived individual AI votes."""
    votes: list[AIVote] = []
    for vote in record.get("ai_votes", []):
        votes.append(
            AIVote(
                model=str(vote.get("model", "Unknown")),
                success=bool(vote.get("success")),
                result=vote.get("result") if isinstance(vote.get("result"), dict) else None,
                error=vote.get("error"),
            )
        )
    if not any(v.success and v.result for v in votes):
        return dict(record.get("consensus") or {})
    try:
        # Preserve the rule used when published; legacy records required two models.
        minimum = record.get('consensus_min_successful', (record.get('consensus') or {}).get('min_successful', 3))
        return build_consensus(votes, min_successful=int(minimum))
    except RuntimeError:
        return dict(record.get("consensus") or {})


def _consensus_flags(record: dict[str, Any]) -> tuple[dict[str, Any], bool, bool, str]:
    rebuilt = _rebuild_consensus_from_record(record)
    mode = str(rebuilt.get("consensus_mode") or "").upper()
    winner_consensus = bool(rebuilt.get("winner_consensus"))
    score_consensus = bool(rebuilt.get("score_consensus"))

    if mode not in {"NORMAL", "OUTCOME_COMMON_SCORE_SPLIT", "NO_COMMON"}:
        if winner_consensus and score_consensus:
            mode = "NORMAL"
        elif winner_consensus:
            mode = "OUTCOME_COMMON_SCORE_SPLIT"
        else:
            mode = "NO_COMMON"

    return rebuilt, winner_consensus, score_consensus, mode


def build_team_history(predictions: dict[str, Any], team: str, limit: int = 5) -> dict[str, Any]:
    rows = []
    for record in predictions.values():
        if not _same_team(record, team) or not record.get("actual"):
            continue
        rows.append(record)

    rows.sort(key=lambda r: r.get("actual", {}).get("updated_at", ""), reverse=True)
    rows = rows[:limit]

    results = []
    prediction_changes = []
    for record in rows:
        home = record.get("home_team", "")
        away = record.get("away_team", "")
        a = record["actual"]
        pred = record.get("consensus", {})
        is_home = home == team
        gf = a.get("home", 0) if is_home else a.get("away", 0)
        ga = a.get("away", 0) if is_home else a.get("home", 0)
        result = "W" if gf > ga else "D" if gf == ga else "L"
        results.append({
            "match": f"{home} - {away}",
            "actual_score": f"{a.get('home')}-{a.get('away')}",
            "result": result,
            "predicted_score": pred.get("score"),
            "predicted_outcome": pred.get("outcome"),
            "outcome_correct": record.get("outcome_correct"),
            "exact_score_correct": record.get("exact_score_correct"),
        })
        change = pred.get("change_vs_previous")
        if change:
            prediction_changes.append(change)

    wins = sum(1 for r in results if r["result"] == "W")
    draws = sum(1 for r in results if r["result"] == "D")
    losses = sum(1 for r in results if r["result"] == "L")
    return {
        "team": team,
        "archived_matches": len(results),
        "results": results,
        "record": f"{wins}W-{draws}D-{losses}L",
        "prediction_changes": prediction_changes[:3],
    }


def build_ai_performance(predictions: dict[str, Any]) -> dict[str, Any]:
    """Season-to-date AI performance across all completed archived predictions."""
    stats: dict[str, dict[str, int | float]] = {}
    for record in predictions.values():
        actual = record.get("actual")
        if not actual:
            continue
        ah, aa = actual.get("home"), actual.get("away")
        if ah is None or aa is None:
            continue
        real_outcome = actual_outcome(ah, aa)
        for vote in record.get("ai_votes", []):
            if not vote.get("success") or not vote.get("result"):
                continue
            model = vote.get("model", "Unknown")
            item = stats.setdefault(model, {"matches": 0, "points": 0, "outcome_correct": 0, "exact_score_correct": 0})
            item["matches"] += 1
            result = vote["result"]
            points = score_prediction(result.get("score"), ah, aa)
            item["points"] += points
            if result.get("outcome") == real_outcome:
                item["outcome_correct"] += 1
            if result.get("score", "").replace(" ", "") == f"{ah}-{aa}":
                item["exact_score_correct"] += 1
    for item in stats.values():
        n = item["matches"] or 1
        item["outcome_accuracy"] = round(item["outcome_correct"] / n * 100)
        item["exact_score_accuracy"] = round(item["exact_score_correct"] / n * 100)
        item["average_points"] = round(item["points"] / n, 2)
    return stats


def grade_record(record: dict[str, Any]) -> None:
    """
    Grade consensus and every successful AI vote after a real result arrives.

    Important:
    - No winner consensus => no consensus points at all.
    - Winner consensus + no exact-score consensus => outcome-only points.
    - Exact-score consensus => normal locked score.
    - Every successful AI vote is always graded independently.
    """
    actual = record.get("actual") or {}
    ah, aa = actual.get("home"), actual.get("away")
    if ah is None or aa is None:
        return

    real_outcome = actual_outcome(ah, aa)
    consensus, winner_consensus, score_consensus, mode = _consensus_flags(record)

    # Always replace stale consensus data with the consensus rebuilt from the
    # individual archived AI votes. This repairs older records that were created
    # with the previous plurality-based engine.
    record["consensus"] = consensus
    consensus["winner_consensus"] = winner_consensus
    consensus["score_consensus"] = score_consensus
    consensus["consensus_mode"] = mode
    record["prediction_mode"] = mode

    if winner_consensus and score_consensus and consensus.get("score"):
        consensus_points = score_prediction(consensus.get("score"), ah, aa)
        exact_correct = consensus.get("score", "").replace(" ", "") == f"{ah}-{aa}"
    elif winner_consensus:
        consensus_points = outcome_points(consensus.get("outcome"), real_outcome)
        exact_correct = False
    else:
        consensus_points = None
        exact_correct = False

    record["consensus_points"] = consensus_points
    record["consensus_winner_applicable"] = winner_consensus
    record["consensus_score_applicable"] = score_consensus
    record["consensus_outcome_correct"] = (
        winner_consensus and consensus.get("outcome") == real_outcome
    )
    record["consensus_exact_score_correct"] = (
        score_consensus
        and bool(consensus.get("score"))
        and consensus.get("score", "").replace(" ", "") == f"{ah}-{aa}"
    )

    # Backward-compatible fields used by team history and older reports.
    record["outcome_correct"] = record["consensus_outcome_correct"]
    record["exact_score_correct"] = record["consensus_exact_score_correct"]
    record["grading_version"] = VERSION

    for vote in record.get("ai_votes", []):
        if not vote.get("success") or not vote.get("result"):
            continue
        result = vote["result"]
        vote["points"] = score_prediction(result.get("score"), ah, aa)
        vote["outcome_correct"] = result.get("outcome") == real_outcome
        vote["exact_score_correct"] = (
            (result.get("score") or "").replace(" ", "") == f"{ah}-{aa}"
        )
