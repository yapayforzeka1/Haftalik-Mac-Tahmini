"""Test isolation: historical production fixtures must not generate TEST warnings."""
from datetime import datetime, timezone

import pytest
import runner
from storage import load_json, save_json


@pytest.mark.parametrize('test_mode', [True, False])
def test_historical_notices_are_only_sent_in_production(monkeypatch, tmp_path, test_mode):
    clock = datetime(2026, 11, 6, tzinfo=timezone.utc)
    fixture = {'id': 42, 'utcDate': '2026-11-03T20:00:00Z', 'status': 'FINISHED',
               'homeTeam': {'name': 'Home'}, 'awayTeam': {'name': 'Away'}}
    production = tmp_path / 'match_predictions.json'
    save_json(production, {})
    before = production.read_bytes()
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'now', lambda: clock)
    monkeypatch.setenv('TEST_MODE', str(test_mode).lower())
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'offline')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'offline')
    monkeypatch.delenv('APPROVED_POLICY_FILE', raising=False)
    monkeypatch.setattr(runner, 'Telegram', lambda token: object())
    class Football:
        def __init__(self, *args): pass
        def get_matches(self): return [fixture]
    monkeypatch.setattr(runner, 'CachedFootball', Football)
    monkeypatch.setattr(runner, 'drain_delivery', lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, 'drain_prediction_updates', lambda *args: None)
    monkeypatch.setattr(runner, 'refresh_results', lambda *args: None)
    def forbidden_pool(*args, **kwargs):
        pytest.fail('Past fixture must not generate an AI request')
    monkeypatch.setattr(runner, 'run_ai_pool', forbidden_pool)
    notices = []
    def deliver(bot, chat, text, receipt, save):
        notices.append(text)
        receipt['complete'] = True
        save()
    monkeypatch.setattr(runner, 'deliver_text', deliver)
    assert runner.main() == 0
    if test_mode:
        assert notices == []
        assert production.read_bytes() == before
        assert (tmp_path / 'test_runtime/match_predictions.json').is_file()
    else:
        assert len(notices) == 1
        assert 'Home' in notices[0]
        state = load_json(tmp_path / 'data/operations.json', {})
        assert state['tracked_fixtures']['42']['missed_notice']['complete']
