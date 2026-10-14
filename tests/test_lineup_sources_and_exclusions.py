"""Offline coverage for real FotMob shapes and Turkish-club cost guard."""
from datetime import datetime, timedelta, timezone

import pytest

import data_provider
import providers
import runner
from ai_pool import AIVote
from learning import new_state

CLOCK = datetime(2026, 10, 14, 18, tzinfo=timezone.utc)


def fixture(home='Real Madrid CF', away='Liverpool FC', minutes=30):
    return {'id': 998, 'utcDate': (CLOCK + timedelta(minutes=minutes)).isoformat(),
            'status': 'TIMED', 'homeTeam': {'name': home, 'id': 100},
            'awayTeam': {'name': away, 'id': 200}}


def starters(side):
    return [{'id': 1000+i, 'name': f'{side} player {i}', 'shirtNumber': str(i)}
            for i in range(11)]


def fotmob_client(monkeypatch, lineup):
    client = data_provider.FotMobClient()
    monkeypatch.setattr(client, 'find_match', lambda *args: {
        'id': 5454, 'home': {'id': 111}, 'away': {'id': 222}})
    monkeypatch.setattr(client, '_get', lambda *args, **kwargs: {
        'content': {'lineup': lineup}})
    return client


def test_current_fotmob_official_payload_does_not_need_confirmed_boolean(monkeypatch):
    client = fotmob_client(monkeypatch, {'lineupType': 'standard',
        'homeTeam': {'id': 111, 'starters': starters('home'), 'formation': '4-3-3'},
        'awayTeam': {'id': 222, 'starters': starters('away')}})
    options = client.get_match_lineup_options('Home', 'Away', CLOCK)
    assert options['reason'] == 'OFFICIAL'
    assert options['official']['status'] == 'ANNOUNCED'
    assert len(options['official']['home']) == 11
    assert options['predicted'] is None


def test_fotmob_predicted_payload_never_counts_as_official(monkeypatch):
    client = fotmob_client(monkeypatch, {'lineupType': 'predicted',
        'homeTeam': {'id': 111, 'starters': starters('home')},
        'awayTeam': {'id': 222, 'starters': starters('away')}})
    assert client.get_match_official_xi('Home', 'Away', CLOCK) is None
    predicted = client.get_match_predicted_xi('Home', 'Away', CLOCK)
    assert predicted['status'] == 'PREDICTED'
    assert predicted['home'][0]['lineup_source'] == 'FOTMOB_PREDICTED'
    assert predicted['home'][0]['availability_verified'] is False
    assert all(p['source_url'].startswith('https://') for p in predicted['away'])
    assert providers.valid_xi(providers.predicted_xi({'predicted_xi': predicted})['home'])


def test_fotmob_rejects_bad_identity_and_unknown_lineup_type(monkeypatch):
    lineup = {'lineupType': 'standard',
              'homeTeam': {'id': 987, 'starters': starters('home')},
              'awayTeam': {'id': 222, 'starters': starters('away')}}
    client = fotmob_client(monkeypatch, lineup)
    assert client.get_match_lineup_options('Home', 'Away', CLOCK)['reason'] == 'TEAM_ID_MISMATCH'
    lineup['homeTeam']['id'] = 111
    lineup['lineupType'] = 'unknown'
    assert client.get_match_lineup_options('Home', 'Away', CLOCK)['reason'] == 'LINEUP_TYPE_UNVERIFIED'
    lineup['lineupType'] = 'standard'
    lineup['confirmed'] = False
    assert client.get_match_official_xi('Home', 'Away', CLOCK) is None


def test_fotmob_does_not_use_bench_as_starting_eleven(monkeypatch):
    client = fotmob_client(monkeypatch, {'lineupType': 'standard',
        'homeTeam': {'id': 111, 'starters': starters('home') + starters('bench')},
        'awayTeam': {'id': 222, 'starters': starters('away')}})
    data = client.get_match_official_xi('Home', 'Away', CLOCK)
    assert data['home'] == [] and len(data['away']) == 11
    assert data['status'] == 'PARTIAL'


def test_source_projected_xi_is_used_at_t30_but_official_wins(monkeypatch):
    monkeypatch.setattr(runner, 'now', lambda: CLOCK)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr(runner, 'prepare_context', lambda *args: {'home': {}, 'away': {}})
    monkeypatch.setattr(runner, 'official_xi', lambda *args: {
        'status': 'PARTIAL', 'home': starters('home'), 'away': [], 'source': 'API-Football'})
    projected = [{**p, 'current_club_confirmed': True, 'unavailable': False,
                  'source_url': 'https://www.fotmob.com/test'} for p in starters('away')]
    calls = []
    monkeypatch.setattr(runner, 'source_predicted_xi', lambda *args: (
        calls.append('provider') or {'status': 'PARTIAL', 'home': [], 'away': projected}))
    monkeypatch.setattr(runner, 'run_ai_pool', lambda *args, **kwargs: (
        calls.append('ai') or [AIVote('offline', False, None, 'OFFLINE')]))
    m = fixture()
    r = runner.new_record(m, new_state())
    assert runner.prepare_prediction(r, m, None, {}, new_state(), lambda: None, float('inf'))
    assert calls == ['provider', 'ai']
    assert r['context']['lineup_availability'] == {'home': 'OFFICIAL', 'away': 'PREDICTED'}
    assert r['research']['predicted_xi']['away'] == projected
    assert r['research']['predicted_xi']['home'] == []


@pytest.mark.parametrize('name', [
    'Fenerbahçe', 'Fenerbahçe SK', 'Fenerbahce Istanbul',
    'Galatasaray', 'Galatasaray SK', 'Galatasaray A.Ş.',
])
def test_excluded_club_name_variants(name):
    assert runner.excluded_club_name(name)


@pytest.mark.parametrize('name', ['Feyenoord Rotterdam', 'LASK Linz',
                                  'Liverpool FC', 'Fener', 'Gala', 'Fenerbahceliler'])
def test_does_not_exclude_unrelated_clubs(name):
    assert not runner.excluded_club_name(name)


def test_excluded_fixtures_never_invoke_lineup_research_or_ai(monkeypatch):
    monkeypatch.setattr(runner, 'now', lambda: CLOCK)
    def forbidden(*args, **kwargs):
        pytest.fail('An excluded match must not invoke lineup/research/AI')
    monkeypatch.setattr(runner, 'official_xi', forbidden)
    monkeypatch.setattr(runner, 'source_predicted_xi', forbidden)
    monkeypatch.setattr(runner, 'run_ai_pool', forbidden)
    for home, away in [('Fenerbahçe SK', 'Liverpool FC'),
                       ('Man City', 'Galatasaray A.Ş.')]:
        m = fixture(home, away)
        r = runner.new_record(m, new_state())
        assert not runner.prepare_prediction(
            r, m, None, {}, new_state(), forbidden, float('inf'))
        assert 'context' not in r and not r['ai_votes']
        assert not runner.prewarm_context(r, m, None, forbidden)
        assert 'context' not in r


def test_main_exclusion_before_prewarm_and_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'now', lambda: CLOCK)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'offline-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'offline-chat')
    monkeypatch.setenv('TEST_MODE', 'false')
    monkeypatch.delenv('APPROVED_POLICY_FILE', raising=False)
    a = fixture('Fenerbahçe SK', 'Liverpool FC', 40)
    b = fixture('Real Madrid', 'Galatasaray A.Ş.', 40)
    c = fixture('LASK Linz', 'Liverpool FC', 40)
    c['id'] = 999
    class Football:
        def __init__(self, *args): pass
        def get_matches(self): return [a, b, c]
    monkeypatch.setattr(runner, 'CachedFootball', Football)
    monkeypatch.setattr(runner, 'Telegram', lambda token: object())
    monkeypatch.setattr(runner, 'drain_delivery', lambda *args: None)
    seen = []
    monkeypatch.setattr(runner, 'prewarm_context', lambda r, m, *args: seen.append(('prewarm', m['id'])))
    monkeypatch.setattr(runner, 'prepare_prediction', lambda r, m, *args, **kw:
                        seen.append(('prediction', m['id'])))
    assert runner.main() == 0
    assert seen == [('prewarm', 999), ('prediction', 999)]
    from storage import load_json
    predictions = load_json(tmp_path / 'match_predictions.json', {})
    assert set(predictions) == {'999'}


def test_old_excluded_record_kept_but_not_delivered(monkeypatch):
    from storage import load_json
    old = {'match_id': '111', 'home_team': 'Fenerbahçe SK', 'away_team': 'Liverpool FC',
           'prediction_ready': True, 'final_sent': False,
           'match_utc': (CLOCK + timedelta(minutes=90)).isoformat(),
           'message_format_version': 4, 'prediction_kind': 'AI'}
    before = old.copy()
    class Bot:
        def photo(self, *args): pytest.fail('Excluded match delivered to Telegram')
    monkeypatch.setattr(runner, 'now', lambda: CLOCK)
    runner.drain_delivery({'111': old}, Bot(), 'chat', lambda: None)
    assert old == before
