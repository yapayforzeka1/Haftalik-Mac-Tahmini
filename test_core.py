from datetime import datetime, timezone
from pathlib import Path
import tempfile

from ai_pool import AIVote, build_prompt
from consensus_engine import build_consensus
from data_provider import build_team_form
from history_engine import build_team_history, build_ai_performance, grade_record, score_prediction
from weekly_report import build_general_snapshot, build_weekly_snapshot, render_general_image, render_weekly_image
from match_report import build_match_group_message, render_match_group_image
from report_engine import build_result_message


def test_consensus():
    votes = [
        AIVote("A", True, {"outcome": "HOME", "score": "2-1", "confidence": 70, "reasons": ["form"]}),
        AIVote("B", True, {"outcome": "HOME", "score": "1-0", "confidence": 65, "reasons": ["xG"]}),
        AIVote("C", True, {"outcome": "DRAW", "score": "1-1", "confidence": 55, "reasons": ["defense"]}),
        AIVote("D", False, error="429"),
    ]
    result = build_consensus(votes)
    assert result["successful_ai"] == 3
    assert result["outcome"] == "HOME"
    assert result["winner_consensus"] is True
    assert result["outcome_share"] == 67
    assert result["score"] is None
    assert result["score_consensus"] is False
    assert result["consensus_mode"] == "OUTCOME_COMMON_SCORE_SPLIT"
    assert result["disagreement"] is True


def test_no_consensus_is_not_plurality():
    votes = [
        AIVote("A", True, {"outcome": "HOME", "score": "2-1", "confidence": 70}),
        AIVote("B", True, {"outcome": "AWAY", "score": "1-2", "confidence": 65}),
        AIVote("C", True, {"outcome": "DRAW", "score": "1-1", "confidence": 55}),
        AIVote("D", True, {"outcome": "HOME", "score": "3-1", "confidence": 50}),
    ]
    result = build_consensus(votes)
    assert result["winner_consensus"] is False
    assert result["score_consensus"] is False
    assert result["outcome"] is None
    assert result["score"] is None
    assert result["consensus_mode"] == "NO_COMMON"


def test_exact_score_consensus_requires_strict_majority():
    votes = [
        AIVote("A", True, {"outcome": "HOME", "score": "2-1", "confidence": 70}),
        AIVote("B", True, {"outcome": "HOME", "score": "2-1", "confidence": 65}),
        AIVote("C", True, {"outcome": "HOME", "score": "1-0", "confidence": 55}),
        AIVote("D", True, {"outcome": "AWAY", "score": "0-1", "confidence": 50}),
        AIVote("E", True, {"outcome": "HOME", "score": "3-1", "confidence": 45}),
    ]
    result = build_consensus(votes)
    assert result["winner_consensus"] is True
    assert result["score_consensus"] is False
    assert result["outcome"] == "HOME"
    assert result["score"] is None
    assert result["top_score"] == "2-1"
    assert result["top_score_votes"] == 2
    assert result["consensus_mode"] == "OUTCOME_COMMON_SCORE_SPLIT"


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

    # Winner has a strict majority (2/3), exact score does not.
    assert record["consensus"]["consensus_mode"] == "OUTCOME_COMMON_SCORE_SPLIT"
    assert record["consensus"]["score"] is None
    assert record["consensus_points"] == 3
    assert record["consensus_winner_applicable"] is True
    assert record["consensus_score_applicable"] is False
    assert record["consensus_outcome_correct"] is True
    assert record["consensus_exact_score_correct"] is False

    assert record["ai_votes"][0]["points"] == 5
    assert record["ai_votes"][1]["points"] == 3
    assert record["ai_votes"][2]["points"] == 0


def test_grade_no_consensus():
    record = {
        "home_team": "Napoli", "away_team": "Arsenal",
        "consensus": {"outcome": "HOME", "score": "1-2"},  # stale old plurality data
        "ai_votes": [
            {"model": "A", "success": True, "result": {"outcome": "AWAY", "score": "1-2"}},
            {"model": "B", "success": True, "result": {"outcome": "HOME", "score": "2-1"}},
            {"model": "C", "success": False, "error": "429"},
        ],
        "actual": {"home": 0, "away": 1, "status": "FINISHED", "updated_at": "2026-09-10T21:00:00+00:00"},
    }
    grade_record(record)

    # Old plurality consensus must be repaired from the individual AI votes.
    assert record["prediction_mode"] == "NO_COMMON"
    assert record["consensus"]["outcome"] is None
    assert record["consensus"]["score"] is None
    assert record["consensus_points"] is None
    assert record["consensus_winner_applicable"] is False
    assert record["ai_votes"][0]["points"] == 3
    assert record["ai_votes"][1]["points"] == 0


def test_result_message_modes():
    no_common = {
        "home_team": "Napoli", "away_team": "Arsenal",
        "actual": {"home": 0, "away": 1},
        "consensus": {
            "outcome": None, "score": None,
            "winner_consensus": False, "score_consensus": False,
            "consensus_mode": "NO_COMMON",
        },
        "consensus_points": None,
        "ai_votes": [
            {"model": "A", "success": True, "result": {"outcome": "AWAY", "score": "1-2"}, "points": 3},
            {"model": "B", "success": True, "result": {"outcome": "HOME", "score": "2-1"}, "points": 0},
        ],
    }
    text = build_result_message(no_common)
    assert "🔴 ORTAK KARAR YOK" in text
    assert "AI Ortak Kararı skoru" not in text
    assert "konsensüs puanı uygulanmadı" in text

    split = {
        "home_team": "PSG", "away_team": "Slovan",
        "actual": {"home": 6, "away": 1},
        "consensus": {
            "outcome": "HOME", "score": None,
            "winner_consensus": True, "score_consensus": False,
            "consensus_mode": "OUTCOME_COMMON_SCORE_SPLIT",
            "outcome_votes": 4,
        },
        "consensus_points": 3,
        "ai_votes": [
            {"model": "A", "success": True, "result": {"outcome": "HOME", "score": "3-0"}, "points": 3},
            {"model": "B", "success": True, "result": {"outcome": "HOME", "score": "3-1"}, "points": 3},
            {"model": "C", "success": True, "result": {"outcome": "HOME", "score": "2-1"}, "points": 3},
            {"model": "D", "success": True, "result": {"outcome": "HOME", "score": "3-0"}, "points": 3},
        ],
    }
    text = build_result_message(split)
    assert "🟢 ORTAK KAZANAN VAR" in text
    assert "🟡 SKORDA ORTAK KARAR YOK" in text
    assert "AI Ortak Kararı skoru" not in text


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
            "consensus": {"outcome": "HOME", "score": "2-1", "successful_ai": 5, "winner_consensus": True, "score_consensus": True, "consensus_mode": "NORMAL"},
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
            "score": "2-1", "score_votes": 3, "score_share": 60, "winner_consensus": True, "score_consensus": True, "consensus_mode": "NORMAL",
        },
    }
    records = [dict(base, match_id=str(i), home_team=h, away_team=a) for i, (h, a) in enumerate([
        ("Juventus", "Dortmund"), ("Real Madrid", "Marseille"),
        ("Benfica", "Qarabag"), ("Tottenham", "Villarreal"),
    ])]
    text = build_match_group_message(records)
    assert "4 MAÇLIK AI TAHMİN PAKETİ" in text
    assert text.count("🤖 AI Ortak Kararı:") == 4
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
    test_grade_no_consensus()
    test_result_message_modes()
    test_team_form()
    test_history()
    test_prompt_is_bounded()
    test_weekly_report_and_general_snapshot()
    test_match_telegram_package()
    print("CORE TESTS OK")
