from __future__ import annotations

from typing import Any


def _same_team(record: dict[str, Any], team: str) -> bool:
    return record.get("home_team") == team or record.get("away_team") == team


def actual_outcome(home: int, away: int) -> str:
    return "HOME" if home > away else "AWAY" if home < away else "DRAW"


def score_prediction(predicted_score: str | None, actual_home: int, actual_away: int) -> int:
    """
    Kilitli puanlama sistemi:
    - Tam skor: 5
    - Kazanan doğru, skor yanlış: 3
    - Beraberlik tahmini + gerçek beraberlik (skor farklı olsa bile): 5
    - Yanlış sonuç: 0

    Not: 2 puan ayrı bir kategori değildir. 5 -> 3 farkı,
    tam skor yerine sadece sonucu bilmenin doğal puan farkıdır.
    """
    score = (predicted_score or "").replace(" ", "")
    actual_score = f"{actual_home}-{actual_away}"
    if score == actual_score:
        return 5

    predicted = None
    try:
        left, right = score.split("-", 1)
        ph, pa = int(left), int(right)
        predicted = actual_outcome(ph, pa)
    except (ValueError, AttributeError):
        pass

    real = actual_outcome(actual_home, actual_away)
    if predicted == "DRAW" and real == "DRAW":
        return 5
    if predicted == real:
        return 3
    return 0


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
    """Grade consensus and every successful AI vote after a real result arrives."""
    actual = record.get("actual") or {}
    ah, aa = actual.get("home"), actual.get("away")
    if ah is None or aa is None:
        return

    real_outcome = actual_outcome(ah, aa)
    consensus = record.get("consensus") or {}
    consensus_score = consensus.get("score")
    consensus["points"] = score_prediction(consensus_score, ah, aa)
    record["consensus_points"] = consensus["points"]
    record["exact_score_correct"] = (consensus_score or "").replace(" ", "") == f"{ah}-{aa}"
    record["outcome_correct"] = consensus.get("outcome") == real_outcome

    for vote in record.get("ai_votes", []):
        if not vote.get("success") or not vote.get("result"):
            continue
        result = vote["result"]
        vote["points"] = score_prediction(result.get("score"), ah, aa)
        vote["outcome_correct"] = result.get("outcome") == real_outcome
        vote["exact_score_correct"] = (result.get("score") or "").replace(" ", "") == f"{ah}-{aa}"
