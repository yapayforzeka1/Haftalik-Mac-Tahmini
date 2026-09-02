from ai_pool import AIVote, build_prompt
from consensus_engine import build_consensus
from data_provider import build_team_form
from history_engine import build_team_history, build_ai_performance


def test_consensus():
    votes = [AIVote("A", True, {"outcome":"HOME","score":"2-1","confidence":70,"reasons":["form"]}),
             AIVote("B", True, {"outcome":"HOME","score":"2-1","confidence":65,"reasons":["xG"]}),
             AIVote("C", True, {"outcome":"DRAW","score":"1-1","confidence":55,"reasons":["defense"]}),
             AIVote("D", False, error="429")]
    result = build_consensus(votes)
    assert result["successful_ai"] == 3 and result["outcome"] == "HOME" and result["outcome_share"] == 67 and result["score"] == "2-1"
    assert result["disagreement"] is True


def test_team_form():
    matches = []
    for i, score in enumerate([(2,1),(1,1),(0,2),(3,0),(1,0)]):
        matches.append({"utcDate":f"2026-08-{20+i:02d}T18:00:00Z","competition":{"name":"Test League"},
            "homeTeam":{"id":1,"name":"Home"},"awayTeam":{"id":2,"name":"Away"},"score":{"fullTime":{"home":score[0],"away":score[1]}}})
    form = build_team_form(matches, 1)
    assert form["last_5"] == "W-D-L-W-W" and form["points_last_5"] == 10 and form["goals_for_last_5"] == 7 and form["goals_against_last_5"] == 4


def test_history():
    archive = {"1":{"home_team":"Home","away_team":"Away","actual":{"home":2,"away":0,"updated_at":"2026-09-01T00:00:00Z"},"consensus":{"outcome":"HOME","score":"2-1"},"outcome_correct":True,"exact_score_correct":False}}
    history = build_team_history(archive, "Home")
    assert history["record"] == "1W-0D-0L"
    assert build_ai_performance(archive) == {}


def test_prompt_is_bounded():
    p = build_prompt("A","B", {"x":"x"*20000}, {"y":"y"*20000}, {"z":"z"*5000})
    assert len(p) < 23000

if __name__ == "__main__":
    test_consensus(); test_team_form(); test_history(); test_prompt_is_bounded(); print("CORE TESTS OK")
