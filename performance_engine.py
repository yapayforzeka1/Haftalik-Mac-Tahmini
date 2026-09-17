from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from config import MODEL_ORDER, REPORT_DELAY_MINUTES, SEASON, TERMINAL_STATUSES
from consensus_engine import build_consensus

POINT_KEYS = ("6", "5", "3", "2", "0")


def actual_outcome(home: int, away: int) -> str:
    if home > away:
        return "HOME"
    if home < away:
        return "AWAY"
    return "DRAW"


def _parse_score(value: str | None) -> tuple[int, int] | None:
    try:
        home, away = str(value or "").replace(" ", "").split("-", 1)
        return int(home), int(away)
    except (TypeError, ValueError):
        return None


def score_points(predicted_score: str | None, predicted_outcome: str | None, actual_home: int, actual_away: int) -> tuple[int, bool, bool]:
    actual = actual_outcome(actual_home, actual_away)
    parsed = _parse_score(predicted_score)
    exact = parsed == (actual_home, actual_away)
    if exact:
        return 6, True, True

    outcome = str(predicted_outcome or "").upper()
    if outcome != actual:
        return 0, False, False
    if actual == "DRAW":
        return 3, False, True
    if parsed is not None and (parsed[0] - parsed[1]) == (actual_home - actual_away):
        return 5, False, True
    return 2, False, True


def grade_record(record: dict[str, Any], actual_home: int, actual_away: int, actual_status: str = "FINISHED") -> dict[str, Any]:
    actual = {"home": actual_home, "away": actual_away, "status": actual_status}
    votes = [dict(v) for v in (record.get("ai_votes", []) or [])]
    consensus = build_consensus(votes)

    for vote in votes:
        vote["points"] = None
        vote["exact_score_correct"] = False
        vote["outcome_correct"] = False
        if not vote.get("success") or not isinstance(vote.get("result"), dict):
            continue
        points, exact, outcome_correct = score_points(vote["result"].get("score"), vote["result"].get("outcome"), actual_home, actual_away)
        vote["points"] = points
        vote["exact_score_correct"] = exact
        vote["outcome_correct"] = outcome_correct

    c_points = None
    c_exact = c_outcome = False
    if consensus.get("winner_consensus"):
        c_points, c_exact, c_outcome = score_points(
            consensus.get("score") if consensus.get("score_consensus") else None,
            consensus.get("outcome"), actual_home, actual_away,
        )

    evaluated = dict(record)
    evaluated["ai_votes"] = votes
    evaluated["actual"] = actual
    evaluated["consensus"] = consensus
    evaluated["consensus_points"] = c_points
    evaluated["consensus_exact_score_correct"] = c_exact
    evaluated["consensus_outcome_correct"] = c_outcome
    evaluated["outcome_correct"] = c_outcome
    evaluated["exact_score_correct"] = c_exact
    return evaluated


def merge_latest_results(predictions: dict[str, Any], status_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, record in predictions.items():
        item = dict(record)
        match = status_map.get(str(key))
        if match:
            status = str(match.get("status", "")).upper()
            score = match.get("score", {}).get("fullTime", {}) if isinstance(match.get("score"), dict) else {}
            home, away = score.get("home"), score.get("away")
            if status == "FINISHED" and home is not None and away is not None:
                item = grade_record(item, int(home), int(away), status)
        if item.get("actual") and not item.get("consensus"):
            actual = item["actual"]
            if actual.get("home") is not None and actual.get("away") is not None:
                item = grade_record(item, int(actual["home"]), int(actual["away"]), str(actual.get("status", "FINISHED")))
        result[str(key)] = item
    return result


def _resolved_fixture_status(match: dict[str, Any], prediction: dict[str, Any] | None) -> str:
    status = str(match.get("status", "")).upper()
    if status == "FINISHED" and prediction and prediction.get("actual"):
        return "EVALUATED"
    if status == "FINISHED":
        return "UNAVAILABLE"
    if status in TERMINAL_STATUSES:
        return status
    return "PENDING"


def matchday_report_due(fixtures: list[dict[str, Any]], now: datetime | None = None) -> bool:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    dates = []
    for match in fixtures:
        value = match.get("utcDate")
        if not value:
            continue
        try:
            dates.append(datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc))
        except ValueError:
            continue
    return bool(dates) and now >= max(dates) + timedelta(minutes=REPORT_DELAY_MINUTES)


def matchday_resolution(fixtures: list[dict[str, Any]], predictions: dict[str, Any]) -> dict[str, Any]:
    rows, counts = [], defaultdict(int)
    for match in fixtures:
        mid = str(match.get("id"))
        status = _resolved_fixture_status(match, predictions.get(mid))
        counts[status] += 1
        rows.append({"match_id": mid, "home": (match.get("homeTeam") or {}).get("name", "?"), "away": (match.get("awayTeam") or {}).get("name", "?"), "utcDate": match.get("utcDate"), "status": status, "provider_status": match.get("status")})
    pending = counts["PENDING"]
    return {"final": pending == 0, "planned_matches": len(fixtures), "evaluated_matches": counts["EVALUATED"], "unavailable_matches": counts["UNAVAILABLE"], "postponed_matches": sum(counts[s] for s in ("POSTPONED", "CANCELLED", "SUSPENDED", "ABANDONED")), "pending_matches": pending, "matches": rows}


def _blank_distribution() -> dict[str, int]:
    return {key: 0 for key in POINT_KEYS}


def build_weekly_stats(predictions: dict[str, Any], matchday: int) -> dict[str, Any]:
    model_stats = {model: {"prediction_opportunities": 0, "successful_predictions": 0, "failed_predictions": 0, "points": 0, "exact": 0, "outcome": 0, "avg": 0, "coverage_pct": 0, "point_distribution": _blank_distribution()} for model in MODEL_ORDER}
    consensus = {"evaluated_matches": 0, "matches": 0, "points": 0, "exact": 0, "outcome": 0, "no_consensus": 0, "score_split": 0, "avg": 0, "coverage_pct": 0, "point_distribution": _blank_distribution()}

    records = [r for r in predictions.values() if int(r.get("matchday") or 0) == int(matchday) and r.get("actual")]
    for record in records:
        consensus["evaluated_matches"] += 1
        c = record.get("consensus") or build_consensus(record.get("ai_votes", []))
        if c.get("winner_consensus"):
            consensus["matches"] += 1
            points = record.get("consensus_points")
            if points is not None:
                consensus["points"] += int(points)
                consensus["point_distribution"][str(int(points))] += 1
            consensus["outcome"] += int(bool(record.get("consensus_outcome_correct")))
            consensus["exact"] += int(bool(record.get("consensus_exact_score_correct")))
            if not c.get("score_consensus"):
                consensus["score_split"] += 1
        else:
            consensus["no_consensus"] += 1

        votes_by_model = {v.get("model"): v for v in record.get("ai_votes", [])}
        for model in MODEL_ORDER:
            item = model_stats[model]
            item["prediction_opportunities"] += 1
            vote = votes_by_model.get(model)
            if not vote or not vote.get("success") or vote.get("points") is None:
                item["failed_predictions"] += 1
                continue
            item["successful_predictions"] += 1
            points = int(vote["points"])
            item["points"] += points
            item["point_distribution"][str(points)] += 1
            item["exact"] += int(bool(vote.get("exact_score_correct")))
            item["outcome"] += int(bool(vote.get("outcome_correct")))

    for item in model_stats.values():
        n, opportunities = int(item["successful_predictions"]), int(item["prediction_opportunities"])
        item["avg"] = round(item["points"] / n, 2) if n else 0
        item["coverage_pct"] = round(n / opportunities * 100, 1) if opportunities else 0
    if consensus["matches"]:
        consensus["avg"] = round(consensus["points"] / consensus["matches"], 2)
    if consensus["evaluated_matches"]:
        consensus["coverage_pct"] = round(consensus["matches"] / consensus["evaluated_matches"] * 100, 1)
    return {"models": model_stats, "consensus": consensus}


def build_weekly_snapshot(predictions: dict[str, Any], matchday: int, resolution: dict[str, Any]) -> dict[str, Any]:
    return {"season": SEASON, "matchday": int(matchday), "status": "FINAL", "finalized_at": datetime.now(timezone.utc).isoformat(), "planned_matches": int(resolution["planned_matches"]), "evaluated_matches": int(resolution["evaluated_matches"]), "unavailable_matches": int(resolution["unavailable_matches"]), "postponed_matches": int(resolution["postponed_matches"]), "pending_matches": int(resolution["pending_matches"]), "matches": resolution["matches"], "stats": build_weekly_stats(predictions, matchday)}


def build_season_snapshot(weekly_reports: dict[str, Any]) -> dict[str, Any]:
    totals = {model: {"matchdays": 0, "prediction_opportunities": 0, "points": 0, "successful_predictions": 0, "failed_predictions": 0, "exact": 0, "outcome": 0, "avg": 0, "coverage_pct": 0, "point_distribution": _blank_distribution()} for model in MODEL_ORDER}
    consensus = {"matchdays": 0, "evaluated_matches": 0, "matches": 0, "points": 0, "exact": 0, "outcome": 0, "no_consensus": 0, "score_split": 0, "avg": 0, "coverage_pct": 0, "point_distribution": _blank_distribution()}

    final_keys = []
    for key, report in sorted(weekly_reports.items(), key=lambda kv: int(kv[0])):
        if report.get("status") != "FINAL":
            continue
        final_keys.append(key)
        stats = report.get("stats", {})
        for model in MODEL_ORDER:
            src, dst = stats.get("models", {}).get(model, {}), totals[model]
            dst["matchdays"] += 1
            for field in ("prediction_opportunities", "points", "successful_predictions", "failed_predictions", "exact", "outcome"):
                dst[field] += int(src.get(field, 0))
            for p in POINT_KEYS:
                dst["point_distribution"][p] += int((src.get("point_distribution") or {}).get(p, 0))
        c = stats.get("consensus", {})
        consensus["matchdays"] += 1
        for field in ("evaluated_matches", "matches", "points", "exact", "outcome", "no_consensus", "score_split"):
            consensus[field] += int(c.get(field, 0))
        for p in POINT_KEYS:
            consensus["point_distribution"][p] += int((c.get("point_distribution") or {}).get(p, 0))

    for item in totals.values():
        n, opportunities = item["successful_predictions"], item["prediction_opportunities"]
        item["avg"] = round(item["points"] / n, 2) if n else 0
        item["coverage_pct"] = round(n / opportunities * 100, 1) if opportunities else 0
    consensus["avg"] = round(consensus["points"] / consensus["matches"], 2) if consensus["matches"] else 0
    consensus["coverage_pct"] = round(consensus["matches"] / consensus["evaluated_matches"] * 100, 1) if consensus["evaluated_matches"] else 0
    return {"season": SEASON, "finalized_matchdays": [int(k) for k in final_keys], "models": totals, "consensus": consensus}
