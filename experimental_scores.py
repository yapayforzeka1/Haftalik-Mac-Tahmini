"""Prospective, immutable, zero-API experimental projections from archived AI votes.

These are diagnostic comparators, NOT consensus, active models, or published picks.
Never backfill a finished fixture as a prospective prediction.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

SCHEMA_VERSION = 1
METHOD_AVERAGE = "al_score_average_v1"
METHOD_MODE = "al_most_frequent_score_v1"


def _outcome(home: int, away: int) -> str:
    return "HOME" if home > away else "AWAY" if away > home else "DRAW"


def eligible_score_votes(votes: Any) -> list[dict]:
    """One consistent, complete prediction per distinct model; no fabricated votes."""
    selected = []
    seen = set()
    if not isinstance(votes, list):
        return selected
    for vote in votes:
        if not isinstance(vote, dict) or vote.get("success") is not True:
            continue
        model = vote.get("model")
        result = vote.get("result")
        if not isinstance(model, str) or not model.strip() or model in seen or not isinstance(result, dict):
            continue
        score = result.get("score")
        if not isinstance(score, str):
            continue
        match = re.fullmatch(r"([0-9]{1,2})-([0-9]{1,2})", score.strip())
        if match is None:
            continue
        home, away = map(int, match.groups())
        # A contradictory outcome is not a valid AI prediction.
        if result.get("outcome") != _outcome(home, away):
            continue
        seen.add(model)
        selected.append({"model": model, "model_id": result.get("model_id") or model,
                         "home": home, "away": away, "score": f"{home}-{away}"})
    return selected


def _half_up_nonnegative(total: int, count: int) -> int:
    """Integer arithmetic avoids Python's banker's rounding and FP error."""
    return (2 * total + count) // (2 * count)


def calculate_experimental_scores(votes: Any, *, match_id: str, created_at: str,
                                  classification: str = "PROSPECTIVE") -> dict:
    """Pure calculation; no provider, filesystem, match results or side effects."""
    if classification not in {"PROSPECTIVE", "BACKTEST"}:
        raise ValueError("Invalid experiment classification")
    if not match_id or not created_at:
        raise ValueError("match_id and created_at required")
    eligible = eligible_score_votes(votes)
    models = [{"model": v["model"], "model_id": v["model_id"]} for v in eligible]
    n = len(eligible)
    raw = json.dumps([(v["model"], v["model_id"], v["score"]) for v in eligible],
                     ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def entry(method: str, score: str | None, reason: str | None) -> dict:
        if score is None:
            outcome = None
        else:
            h, a = (int(x) for x in score.split("-"))
            outcome = _outcome(h, a)
        return {"match_id": str(match_id), "method": method, "version": SCHEMA_VERSION,
                "classification": classification, "predicted_score": score,
                "predicted_outcome": outcome, "valid_ai_count": n,
                "models_used": models, "created_at": created_at,
                "failure_reason": reason, "source_votes_sha256": digest}

    if n >= 3:
        avg = f"{_half_up_nonnegative(sum(v['home'] for v in eligible), n)}-{_half_up_nonnegative(sum(v['away'] for v in eligible), n)}"
        average = entry(METHOD_AVERAGE, avg, None)
    else:
        average = entry(METHOD_AVERAGE, None, "MIN_3_VALID_AI")

    counts = Counter(v["score"] for v in eligible)
    if not counts or max(counts.values()) < 2:
        frequent = entry(METHOD_MODE, None, "NO_REPEATED_SCORE")
    else:
        max_count = max(counts.values())
        winners = [score for score, count in counts.items() if count == max_count]
        frequent = (entry(METHOD_MODE, winners[0], None) if len(winners) == 1
                    else entry(METHOD_MODE, None, "TIED_TOP_SCORES"))
    return {"schema_version": SCHEMA_VERSION, "classification": classification,
            "methods": {METHOD_AVERAGE: average, METHOD_MODE: frequent}}


def freeze_prospective_experiments(record: dict, *, created_at: str) -> bool:
    """Write at most once, strictly pre-kickoff; never rewrite an existing experiment."""
    if "experimental_predictions" in record:
        return False
    kickoff = record.get("match_utc")
    try:
        start = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
        creation = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if start.tzinfo is None or creation.tzinfo is None or creation >= start:
            return False
    except (TypeError, ValueError, OverflowError):
        return False
    record["experimental_predictions"] = calculate_experimental_scores(
        record.get("ai_votes"), match_id=str(record.get("match_id")),
        created_at=created_at, classification="PROSPECTIVE")
    return True
