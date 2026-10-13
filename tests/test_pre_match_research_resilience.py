"""Offline checks for factual staging and honest research-failure recovery."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import sys

import pytest

import runner
import providers
from ai_pool import AIVote
from learning import new_state
from research_engine import structured_research
from providers import CachedFootball

NOW = datetime(2026, 10, 13, 19, 30, tzinfo=timezone.utc)


def match(minutes=30):
    return {
        'id': 575343,
        'utcDate': (NOW + timedelta(minutes=minutes)).isoformat(),
        'status': 'TIMED',
        'homeTeam': {'id': 11, 'name': 'Home Club'},
        'awayTeam': {'id': 22, 'name': 'Away Club'},
    }


def form(team_id):
    return {
        'team_id': team_id,
        'last_5': {
            'matches': [
                {'date': '2026-10-10T11:00:00Z', 'competition': 'League',
                 'opponent': 'Team One', 'venue': 'HOME',
                 'goals_for': 2, 'goals_against': 1, 'result': 'W'},
                {'date': '2026-10-04T11:00:00Z', 'competition': 'League',
                 'opponent': 'Team Two', 'venue': 'AWAY',
                 'goals_for': 1, 'goals_against': 1, 'result': 'D'},
            ],
            'home_split_last_5': {'matches': 1, 'record': '1W-0D-0L',
                                  'goals_for': 2, 'goals_against': 1},
            'away_split_last_5': {'matches': 1, 'record': '0W-1D-0L',
                                  'goals_for': 1, 'goals_against': 1},
            'matches_last_14_days': 2,
            'rest_days_before_match': 3.0,
        },
        'standings': {'position': 7, 'points': 3, 'playedGames': 1},
    }


def test_structured_fallback_has_provenance_but_never_claims_grounded_news():
    context = {'home': form(11), 'away': form(22),
               'official_xi': {'status': 'NOT_ANNOUNCED'}}
    result = structured_research(context, 'QUOTA_OR_RATE_LIMIT')
    assert result['status'] == 'STRUCTURED_ONLY'
    assert result['source_kind'] == 'FOOTBALL_DATA_API'
    assert result['provider_warning'] == 'QUOTA_OR_RATE_LIMIT'
    assert 'Son 2 doğrulanmış maç: W-D' in result['home']['form']
    assert '3 gol attı, 2 gol yedi' in result['away']['goals_trend']
    assert result['league_context']['home']['points'] == 3
    assert result['fixture_congestion']['away'].startswith('Son maçtan itibaren 3.0 gün')
    assert result['source_refs'][0]['team_id'] == 11
    assert result['predicted_xi'] == {'home': [], 'away': []}
    assert result['news'] == []
    assert result['official_xi']['status'] == 'NOT_ANNOUNCED'


def test_empty_history_does_not_invent_form_or_xi():
    result = structured_research({'home': {}, 'away': {}})
    assert 'mevcut değil' in result['home']['form']
    assert result['score_drivers'] == []
    assert result['source_refs'] == []


def test_prewarms_without_invoking_any_ai_then_waits_until_last_30(monkeypatch):
    monkeypatch.setattr(runner, 'now', lambda: NOW)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr(runner, 'official_xi', lambda *a: None)
    calls = {'context': 0, 'pool': 0}
    def fetch(*args):
        calls['context'] += 1
        return {'home': form(11), 'away': form(22)}
    monkeypatch.setattr(runner, 'prepare_context', fetch)
    monkeypatch.setattr(runner, 'run_ai_pool', lambda *a, **k: (
        calls.__setitem__('pool', calls['pool'] + 1) or [AIVote('Offline', False, None, 'OFFLINE')]))

    scheduled = match(60)
    r = runner.new_record(scheduled, new_state())
    assert runner.prewarm_context(r, scheduled, None, lambda: None)
    assert calls == {'context': 1, 'pool': 0}
    assert not r.get('inputs_frozen')
    assert not r.get('research')
    assert not runner.prepare_prediction(r, scheduled, None, {}, new_state(), lambda: None, float('inf'))
    assert calls == {'context': 1, 'pool': 0}
    scheduled['utcDate'] = (NOW + timedelta(minutes=30)).isoformat()
    assert runner.prepare_prediction(r, scheduled, None, {}, new_state(), lambda: None, float('inf'))
    assert calls == {'context': 1, 'pool': 1}
    assert r['research']['status'] == 'STRUCTURED_ONLY'
    assert r['context']['predicted_xi']['home'] == []


def test_respects_official_xi_on_prediction_after_prewarm(monkeypatch):
    monkeypatch.setattr(runner, 'now', lambda: NOW)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr(runner, 'prepare_context', lambda *a: {'home': form(11), 'away': form(22)})
    eleven = [{'name': f'Player{i}'} for i in range(11)]
    monkeypatch.setattr(runner, 'official_xi', lambda *a: {
        'status': 'ANNOUNCED', 'home': eleven, 'away': eleven,
        'source': 'football-data.org'})
    monkeypatch.setattr(runner, 'run_ai_pool', lambda *a, **k: [AIVote('Offline', False, None, 'OFFLINE')])
    m = match(60)
    r = runner.new_record(m, new_state())
    runner.prewarm_context(r, m, None, lambda: None)
    assert runner.prepare_prediction(r, m, None, {}, new_state(), lambda: None, float('inf'))
    assert r['context']['official_xi']['status'] == 'ANNOUNCED'
    assert r['research']['official_xi']['status'] == 'ANNOUNCED'


def test_gemini_quota_failure_opens_gate_for_next_fixture(monkeypatch):
    monkeypatch.setattr(runner, 'now', lambda: NOW)
    monkeypatch.setenv('GEMINI_API_KEY', 'fake-test-key')
    monkeypatch.setattr(runner, 'official_xi', lambda *a: None)
    monkeypatch.setattr(runner, 'prepare_context', lambda *a: {'home': form(11), 'away': form(22)})
    monkeypatch.setattr(runner, 'run_ai_pool', lambda *a, **k: [AIVote('Offline', False, None, 'OFFLINE')])
    calls = []
    def research(*args):
        calls.append(1)
        raise RuntimeError('429 test-quota')
    monkeypatch.setattr(runner, 'research_match', research)
    monkeypatch.setitem(sys.modules, 'google.genai', SimpleNamespace(Client=lambda **kwargs: object()))
    gate = {}
    changes = []
    for match_id in (11, 12):
        m = match()
        m['id'] = match_id
        r = runner.new_record(m, new_state())
        assert runner.prepare_prediction(
            r, m, None, {}, new_state(), lambda: None, float('inf'),
            research_gate=gate, save_research_gate=lambda: changes.append(gate.copy())
        )
        assert r['research']['status'] == 'STRUCTURED_ONLY'
        assert r['research']['provider_warning'] in ('QUOTA_OR_RATE_LIMIT','PROVIDER_COOLDOWN')
    assert len(calls) == 1
    assert len(changes) == 1
    assert 'until' in gate


def test_team_results_cached_and_sorted_without_second_api_request(monkeypatch):
    monkeypatch.setenv('FOOTBALL_DATA_API_KEY', 'offline-key')
    monkeypatch.setattr(providers.time, 'sleep', lambda sec: None)
    result = {
        'matches': [
            {'id': 2, 'utcDate': '2026-10-09T12:00:00Z', 'status': 'FINISHED'},
            {'id': 1, 'utcDate': '2026-10-08T12:00:00Z', 'status': 'FINISHED'},
            {'id': 3, 'utcDate': '2026-10-20T12:00:00Z', 'status': 'FINISHED'},
        ]
    }
    hits = []
    def mock_get(url, **kw):
        hits.append((url, kw))
        return SimpleNamespace(status_code=200, json=lambda: result)
    monkeypatch.setattr(providers.requests, 'get', mock_get)
    cache = {}
    f = CachedFootball(cache, lambda: None)
    rows = f.get_team_matches(11, NOW)
    assert [r['id'] for r in rows] == [2,1]
    assert [r['id'] for r in f.get_team_matches(11, NOW)] == [2,1]
    assert len(hits) == 1
    assert '/teams/11/matches' in hits[0][0]


def test_image_status_does_not_claim_form_when_history_is_empty():
    from match_report import _data_status
    r = {'context': {
        'home': {'last_5': {'matches': []}},
        'away': {'last_5': {'matches': []}},
    }, 'research': {'status': 'STRUCTURED_ONLY'}}
    flags = dict(_data_status(r))
    assert flags['Form'] is False
    assert flags['Güncel araştırma'] is False
