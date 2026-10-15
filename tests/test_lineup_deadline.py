"""Offline coverage for 60-to-30 minute XI policy and split provider XIs."""

from datetime import datetime, timedelta, timezone

import pytest

import data_provider
import providers
import runner
from ai_pool import AIVote
from learning import new_state
from messages import lineup_text

CLOCK = datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)


def eleven(side):
    return [{'name': f'{side} {number}'} for number in range(11)]


def fixture(clock, mins):
    return {'id': 707, 'utcDate': (clock + timedelta(minutes=mins)).isoformat(),
            'status': 'TIMED', 'homeTeam': {'name': 'A', 'id': 11},
            'awayTeam': {'name': 'B', 'id': 22}}


def test_partial_provider_preserves_other_team(monkeypatch):
    monkeypatch.delenv('API_FOOTBALL_KEY', raising=False)
    class Football:
        def get_match_details(self, _):
            return {'homeTeam': {'lineup': eleven('home')}, 'awayTeam': {'lineup': []}}
    class FotMob:
        def get_match_official_xi(self, *args):
            return {'status': 'PARTIAL', 'home': [], 'away': eleven('away'), 'source': 'FotMob'}
    monkeypatch.setattr(providers, 'FotMobClient', FotMob)
    result = providers.official_xi(Football(), fixture(CLOCK, 60))
    assert result['status'] == 'ANNOUNCED'
    assert result['home'] == eleven('home')
    assert result['away'] == eleven('away')
    assert result['home_source'] == 'football-data.org'
    assert result['away_source'] == 'FotMob'


def test_partial_xi_persists_over_unavailable_provider():
    saved = providers.merge_official_xi(None, {'home': eleven('home'),
        'away': [], 'source': 'FotMob'})
    assert saved['status'] == 'PARTIAL'
    assert providers.merge_official_xi(saved, None)['home'] == eleven('home')
    assert providers.merge_official_xi(saved, {'home': [], 'away': eleven('away'),
        'source': 'API-Football'})['status'] == 'ANNOUNCED'
    assert providers.merge_official_xi(None, {'home': eleven('home')[:10]})['status'] == 'NOT_ANNOUNCED'


def test_waits_and_polls_without_ai_then_uses_mix_at_t30(monkeypatch):
    current = [CLOCK]
    monkeypatch.setattr(runner, 'now', lambda: current[0])
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr(runner, 'prepare_context', lambda *a: {'home': {}, 'away': {}})
    calls = {'xi': 0, 'ai': 0}
    def fetch(*_):
        calls['xi'] += 1
        return {'status': 'PARTIAL', 'home': eleven('home'), 'away': [], 'source': 'FotMob'}
    monkeypatch.setattr(runner, 'official_xi', fetch)
    def pool(*args, **kwargs):
        calls['ai'] += 1
        return [AIVote('offline', False, None, 'OFFLINE')]
    monkeypatch.setattr(runner, 'run_ai_pool', pool)
    r = runner.new_record(fixture(current[0], 60), new_state())
    m = fixture(current[0], 60)
    assert not runner.prepare_prediction(r, m, None, {}, new_state(), lambda: None, float('inf'))
    assert calls == {'xi': 1, 'ai': 0}
    assert r['context']['official_xi']['status'] == 'PARTIAL'
    current[0] += timedelta(minutes=1)
    assert not runner.prepare_prediction(r, m, None, {}, new_state(), lambda: None, float('inf'))
    assert calls == {'xi': 1, 'ai': 0}  # throttled
    current[0] += timedelta(minutes=4)
    assert not runner.prepare_prediction(r, m, None, {}, new_state(), lambda: None, float('inf'))
    assert calls == {'xi': 2, 'ai': 0}
    current[0] += timedelta(minutes=25)  # T-30
    assert runner.prepare_prediction(r, m, None, {}, new_state(), lambda: None, float('inf'))
    assert calls == {'xi': 3, 'ai': 1}
    assert r['context']['lineup_availability'] == {'home': 'OFFICIAL', 'away': 'MISSING'}
    assert lineup_text(r) == '⚠️ Kadro eksik'  # not falsely claimed complete
    assert r['inputs_frozen']


def test_early_full_official_does_not_wait_until_t30(monkeypatch):
    monkeypatch.setattr(runner, 'now', lambda: CLOCK)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr(runner, 'prepare_context', lambda *a: {'home': {}, 'away': {}})
    monkeypatch.setattr(runner, 'official_xi', lambda *_: {'status': 'ANNOUNCED',
        'home': eleven('home'), 'away': eleven('away'), 'source': 'FotMob'})
    calls = []
    monkeypatch.setattr(runner, 'run_ai_pool', lambda *args, **kw:
        (calls.append(1) or [AIVote('offline', False, None, 'OFFLINE')]))
    m = fixture(CLOCK, 52)
    r = runner.new_record(m, new_state())
    assert runner.prepare_prediction(r, m, None, {}, new_state(), lambda: None, float('inf'))
    assert calls == [1]
    assert r['context']['lineup_availability'] == {'home': 'OFFICIAL', 'away': 'OFFICIAL'}


def test_fotmob_partial_explicitly_confirmed(monkeypatch):
    client = data_provider.FotMobClient()
    monkeypatch.setattr(client, 'find_match', lambda *args:
        {'id': 55, 'home': {'id': 1}, 'away': {'id': 2}})
    monkeypatch.setattr(client, '_get', lambda *args, **kwargs: {'content': {'lineup': {
        'confirmed': True, 'lineups': [
            {'teamId': 1, 'players': eleven('home')},
            {'teamId': 2, 'players': []},
        ]}}})
    result = client.get_match_official_xi('A', 'B', CLOCK)
    assert result['status'] == 'PARTIAL' and len(result['home']) == 11
    assert result['away'] == []
    # An unconfirmed FotMob roster must never be accepted.
    monkeypatch.setattr(client, '_get', lambda *args, **kwargs: {'content': {
        'lineup': {'confirmed': False, 'lineups': [{'teamId': 1, 'players': eleven('home')}]}}})
    assert client.get_match_official_xi('A', 'B', CLOCK) is None


def test_predicted_xi_mix_status_is_visible():
    predicted = [dict(name=f'B {i}', current_club_confirmed=True, unavailable=False,
                      source_url='https://example.org/source') for i in range(11)]
    context = {'official_xi': {'status': 'PARTIAL', 'home': eleven('home'), 'away': []},
               'predicted_xi': providers.predicted_xi({'predicted_xi': {'away': predicted}})}
    assert runner.lineup_availability(context) == {'home': 'OFFICIAL', 'away': 'PREDICTED'}
    assert lineup_text({'context': context}) == '⚠️ Karma 11 (resmî/tahmini)'


def test_api_football_partial_lineup(monkeypatch):
    client = data_provider.APIFootballClient(api_key='offline-test-key')
    monkeypatch.setattr(client, 'find_fixture', lambda *args: {
        'fixture': {'id': 654}, 'teams': {
            'home': {'name': 'A', 'id': 11}, 'away': {'name': 'B', 'id': 22}}})
    monkeypatch.setattr(client, 'get_lineups', lambda *args: [
        {'team': {'id': 11, 'name': 'A'},
         'startXI': [{'player': {'name': f'home {i}'}} for i in range(11)]},
    ])
    result = client.get_match_official_xi('A', 'B', CLOCK)
    assert result['status'] == 'PARTIAL'
    assert len(result['home']) == 11 and result['away'] == []


def test_source_predicted_xi_preserves_verified_official_side_without_ai_research(monkeypatch):
    monkeypatch.setattr(runner, 'now', lambda: CLOCK)
    monkeypatch.setenv('GEMINI_API_KEY', 'offline-mocked-key')
    monkeypatch.setattr(runner, 'prepare_context', lambda *a: {'home': {}, 'away': {}})
    monkeypatch.setattr(runner, 'official_xi', lambda *_: {
        'status': 'PARTIAL', 'home': eleven('home'), 'away': [], 'source': 'FotMob'})
    probable = [dict(name=f'Probable {i}', current_club_confirmed=True,
                     unavailable=False, source_url='https://example.org/team-preview')
                for i in range(11)]
    monkeypatch.setattr(runner, 'source_predicted_xi', lambda *_: {'away': probable})
    monkeypatch.setattr(runner, 'research_match', lambda *_: pytest.fail('No AI research should run'))
    monkeypatch.setattr(runner, 'run_ai_pool', lambda *args, **kwargs:
                        [AIVote('offline', False, None, 'OFFLINE')])
    m = fixture(CLOCK, 30)
    r = runner.new_record(m, new_state())
    assert runner.prepare_prediction(r, m, None, {}, new_state(), lambda: None, float('inf'))
    assert r['context']['lineup_availability'] == {'home': 'OFFICIAL', 'away': 'PREDICTED'}
    assert r['context']['official_xi']['away'] == []
    assert r['context']['predicted_xi']['away'] == probable
    assert r['research']['status'] == 'STRUCTURED_ONLY'
