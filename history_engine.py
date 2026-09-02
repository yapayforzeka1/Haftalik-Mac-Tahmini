from __future__ import annotations

from collections import Counter
from typing import Any


def _same_team(record: dict[str, Any], team: str) -> bool:
    return record.get("home_team") == team or record.get("away_team") == team


def build_team_history(predictions: dict[str, Any], team: str, limit: int = 5) -> dict[str, Any]:
    """Summarize previous archived matches for a team without replacing live data."""
    rows = []
    for record in predictions.values():
        if not _same_team(record, team) or not record.get("actual"):
            continue
        actual = record["actual"]
        rows.append(record)

    rows.sort(key=lambda r: r.get("actual", {}).get("updated_at", ""), reverse=True)
    rows = rows[:limit]

    results = []
    prediction_changes = []
    for record in rows:
        home = record.get("home_team", "")
        away = record.get("away_team", "")
        a = record.get("actual", {})
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
    stats: dict[str, dict[str, int]] = {}
    for record in predictions.values():
        actual = record.get("actual")
        if not actual:
            continue
        for vote in record.get("ai_votes", []):
            model = vote.get("model", "Unknown")
            item = stats.setdefault(model, {"matches": 0, "outcome_correct": 0, "exact_score_correct": 0})
            item["matches"] += 1
            result = vote.get("result") or {}
            actual_outcome = "HOME" if actual.get("home", 0) > actual.get("away", 0) else "AWAY" if actual.get("home", 0) < actual.get("away", 0) else "DRAW"
            if result.get("outcome") == actual_outcome:
                item["outcome_correct"] += 1
            if result.get("score", "").replace(" ", "") == f"{actual.get('home')}-{actual.get('away')}":
                item["exact_score_correct"] += 1
    for item in stats.values():
        n = item["matches"] or 1
        item["outcome_accuracy"] = round(item["outcome_correct"] / n * 100)
        item["exact_score_accuracy"] = round(item["exact_score_correct"] / n * 100)
    return stats
