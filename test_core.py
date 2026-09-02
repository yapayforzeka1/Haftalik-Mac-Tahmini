from datetime import datetime, timezone
from pathlib import Path
import tempfile

from ai_pool import AIVote, build_prompt
from consensus_engine import build_consensus
from data_provider import build_team_form
from history_engine import build_team_history, build_ai_performance, grade_record, score_prediction
from weekly_report import build_general_snapshot, build_weekly_snapshot, render_general_image, render_weekly_image
from match_report import build_match_group_message, render_match_group_image


def test_consensus():
    votes = [
        AIVote("A", True, {"outcome": "HOME", "score": "2-1", "confidence": 70, "reasons": ["form"]}),
        AIVote("B", True, {"outcome": "HOME", "score": "2-1", "confidence": 65, "reasons": ["xG"]}),
        AIVote("C", True, {"outcome": "DRAW", "score": "1-1", "confidence": 55, "reasons": ["defense"]}),
        AIVote("D", False, error="429"),
    ]
    result = build_consensus(votes)
    assert result["successful_ai"] == 3
    assert result["outcome"] == "HOME"
    assert result["outcome_share"] == 67
    assert result["score"] == "2-1"
    assert result["disagreement"] is True


def test_locked_scoring_rules():
    # Exact score = 5
    assert score_prediction("2-1", 2, 1) == 5
    # Winner right, score wrong = 3 (the 2-point gap is not a separate category)
    assert score_prediction("2-1", 3, 1) == 3
    assert score_prediction("2-1", 5, 0) == 3
    # Any draw prediction + any actual draw = 5
    assert score_prediction("1-1", 2, 2) == 5
    assert score_prediction("0-0", 3, 3) == 5
    assert score_prediction("2-2", 1, 1) == 5
    # Wrong outcome = 0
    assert score_prediction("2-1", 0, 1) == 0


def test_grade_record():
    record = {
        "home_team": "Home", "away_team": "Away",
        "consensus": {"outcome": "HOME", "score": "2-1"},
        "ai_votes": [
            {"model": "A", "success": True, "result": {"outcome": "HOME", "score": "2-1"}},
            {"model": "B", "success": True, "result": {"outcome": "HOME", "score": "1-0"}},
            {"model": "C", "success": True, "result": {"outcome": "AWAY", "score": "0-1"}},
            {"model": "D", "success": False, "error": "429"},
        ],
        "actual": {"home": 2, "away": 1, "status": "FINISHED", "updated_at": "2026-09-10T21:00:00+00:00"},
    }
    grade_record(record)
    assert record["consensus_points"] == 5
    assert record["ai_votes"][0]["points"] == 5
    assert record["ai_votes"][1]["points"] == 3
    assert record["ai_votes"][2]["points"] == 0


def test_team_form():
    matches = []
    for i, score in enumerate([(2, 1), (1, 1), (0, 2), (3, 0), (1, 0)]):
        matches.append({
            "utcDate": f"2026-08-{20+i:02d}T18:00:00Z",
            "competition": {"name": "Test League"},
            "homeTeam": {"id": 1, "name": "Home"},
            "awayTeam": {"id": 2, "name": "Away"},
            "score": {"fullTime": {"home": score[0], "away": score[1]}},
        })
    form = build_team_form(matches, 1)
    assert form["last_5"] == "W-D-L-W-W"
    assert form["points_last_5"] == 10
    assert form["goals_for_last_5"] == 7
    assert form["goals_against_last_5"] == 4


def test_history():
    archive = {
        "1": {
            "home_team": "Home", "away_team": "Away",
            "actual": {"home": 2, "away": 0, "updated_at": "2026-09-01T00:00:00Z"},
            "consensus": {"outcome": "HOME", "score": "2-1"},
            "outcome_correct": True, "exact_score_correct": False,
        }
    }
    history = build_team_history(archive, "Home")
    assert history["record"] == "1W-0D-0L"
    assert build_ai_performance(archive) == {}


def test_prompt_is_bounded():
    prompt = build_prompt("A", "B", {"x": "x" * 20000}, {"y": "y" * 20000}, {"z": "z" * 5000})
    assert len(prompt) < 23000


def test_weekly_report_and_general_snapshot():
    predictions = {}
    planned = []
    for i in range(18):
        match_id = str(1000 + i)
        planned.append({
            "id": int(match_id),
            "matchday": 1,
            "status": "FINISHED",
            "utcDate": f"2026-09-10T{17 + i // 6:02d}:{(i % 6) * 10:02d}:00Z",
            "homeTeam": {"name": f"Home {i+1}"},
            "awayTeam": {"name": f"Away {i+1}"},
        })
        votes = []
        for model in ["Gemini 3.6 Flash", "Mistral Small Latest", "Groq Qwen 3.6 27B", "Cohere Command A+", "Groq GPT-OSS 120B"]:
            votes.append({"model": model, "success": True, "result": {"outcome": "HOME", "score": "2-1"}, "points": 5, "outcome_correct": True, "exact_score_correct": True})
        predictions[match_id] = {
            "match_id": match_id, "matchday": 1, "home_team": f"Home {i+1}", "away_team": f"Away {i+1}",
            "match_time": f"10.09.2026 {17 + i // 6:02d}:{(i % 6) * 10:02d}",
            "match_utc": planned[-1]["utcDate"],
            "prediction_created_at": "2026-09-10T10:00:00+00:00",
            "actual": {"home": 2, "away": 1, "status": "FINISHED", "updated_at": "2026-09-10T21:00:00+00:00"},
            "ai_votes": votes,
            "consensus": {"outcome": "HOME", "score": "2-1", "successful_ai": 5},
            "consensus_points": 5, "outcome_correct": True, "exact_score_correct": True,
        }

    snapshot = build_weekly_snapshot(predictions, 1, planned)
    assert snapshot["completed_evaluated_matches"] == 18
    assert snapshot["stats"]["models"]["Gemini 3.6 Flash"]["points"] == 90
    assert snapshot["stats"]["consensus"]["points"] == 90

    reports = {"1": snapshot}
    general = build_general_snapshot(reports)
    assert general["models"]["Cohere Command A+"]["total_points"] == 90
    assert general["consensus"]["total_points"] == 90

    with tempfile.TemporaryDirectory() as tmp:
        import weekly_report
        old_dir = weekly_report.REPORT_DIR
        weekly_report.REPORT_DIR = Path(tmp)
        try:
            assert render_weekly_image(snapshot, predictions).exists()
            assert render_general_image(reports).exists()
        finally:
            weekly_report.REPORT_DIR = old_dir


def test_match_telegram_package():
    base = {
        "matchday": 1, "match_utc": "2026-09-08T16:45:00+00:00",
        "match_time": "08.09.2026 19:45", "consensus": {
            "successful_ai": 5, "outcome": "HOME", "outcome_votes": 4, "outcome_share": 80,
            "score": "2-1", "score_votes": 3, "score_share": 60,
        },
    }
    records = [dict(base, match_id=str(i), home_team=h, away_team=a) for i, (h, a) in enumerate([
        ("Juventus", "Dortmund"), ("Real Madrid", "Marseille"),
        ("Benfica", "Qarabag"), ("Tottenham", "Villarreal"),
    ])]
    text = build_match_group_message(records)
    assert "4 MAÇLIK AI TAHMİN PAKETİ" in text
    assert text.count("🤖 Kazanan:") == 4
    assert "Puanlama maç sonucu" in text
    import match_report
    with tempfile.TemporaryDirectory() as tmp:
        old_dir = match_report.REPORT_DIR
        match_report.REPORT_DIR = Path(tmp)
        try:
            assert render_match_group_image(records).exists()
            assert render_match_group_image(records[:1]).exists()
        finally:
            match_report.REPORT_DIR = old_dir


if __name__ == "__main__":
    test_consensus()
    test_locked_scoring_rules()
    test_grade_record()
    test_team_form()
    test_history()
    test_prompt_is_bounded()
    test_weekly_report_and_general_snapshot()
    test_match_telegram_package()
    print("CORE TESTS OK")
