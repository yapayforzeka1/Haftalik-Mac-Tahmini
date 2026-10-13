"""Offline regression tests for the score/confidence visual ordering.

No AI calls, Telegram sending, research, or remote crest downloads.
"""
import copy
import json
from pathlib import Path

from PIL import Image

import match_report


def test_confidence_sort_is_descending_and_does_not_change_archive():
    record = {"ai_votes": [
        {"model": "Qwen", "success": True, "result": {"score": "2-1", "outcome": "HOME", "confidence": 60}},
        {"model": "Gemini", "success": False, "result": None, "error": "429"},
        {"model": "GPT-OSS", "success": True, "result": {"score": "1-0", "outcome": "HOME", "confidence": 0}},
        {"model": "Clef", "success": True, "result": {"score": "2-1", "outcome": "HOME", "confidence": 95}},
        {"model": "Cohere", "success": True, "result": {"score": "0-1", "outcome": "AWAY", "confidence": 60}},
    ]}
    archived = copy.deepcopy(record)
    ordered = match_report._ordered_ai_votes(record)
    assert [v["model"] for v in ordered] == ["Clef", "Qwen", "Cohere", "Gemini", "GPT-OSS"]
    assert record == archived
    assert [match_report._vote_confidence(v) for v in ordered] == [95.0, 60.0, 60.0, None, None]


def test_non_provided_confidence_is_not_fabricated():
    for confidence in (None, 0, -2, 101, float('nan'), "78", True):
        vote = {"model": "Qwen", "success": True, "result": {"confidence": confidence}}
        assert match_report._vote_confidence(vote) is None
    assert match_report._vote_confidence({"success": False, "result": {"confidence": 100}}) is None


def test_seven_real_fixture_records_render_without_record_mutation(monkeypatch, tmp_path):
    # This file comes from the user-provided snapshot and is loaded read-only.
    data = json.loads(Path('match_predictions.json').read_text(encoding='utf-8'))
    rows = [data[str(mid)] for mid in range(575343, 575350)]
    before = copy.deepcopy(rows)
    monkeypatch.setattr(match_report, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(match_report, "_load_crest", lambda *a, **k: None)
    result = match_report.render_match_group_image(rows)
    with Image.open(result) as img:
        assert img.width == 1480
        assert 1450 <= img.height <= 1900
    assert rows == before
    # An existing prediction never triggers a second model request just for display.
    assert match_report._vote_confidence(match_report._ordered_ai_votes(rows[0])[0]) is not None
