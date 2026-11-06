"""Clef transport and state regressions; all HTTP responses are local fakes."""
import io
import json
import urllib.error

import pytest
import ai_pool


def response():
    return {'success': True, 'result': {'answers': {
        'result': {'choice': '1', 'probabilities': {'1': 0.6}},
        'score': {'choice': '1_0', 'probabilities': {'1_0': 0.6}}}}}


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN', 'private-key')
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID', 'private-account')
    monkeypatch.setenv('CLEF_ENABLED', 'true')
    for key in ('GEMINI_API_KEY', 'COHERE_API_KEY', 'GROQ_API_KEY'):
        monkeypatch.delenv(key, raising=False)


def fake_transport(monkeypatch, sequence):
    calls = []
    def request(req, **kwargs):
        calls.append((json.loads(req.data), kwargs))
        item = sequence[len(calls)-1]
        if isinstance(item, Exception): raise item
        return io.StringIO(json.dumps(item) if not isinstance(item, str) else item)
    monkeypatch.setattr('urllib.request.urlopen', request)
    return calls


def test_long_state_keeps_valid_json_and_research(enabled, monkeypatch):
    calls = fake_transport(monkeypatch, [response()])
    context = {'long_field': 'x'*20000, 'home': {'team_id': 1}}
    research = {'official_xi': ['player'+str(i) for i in range(11)]}
    result = ai_pool._cloudflare_clef('Home', 'Away', context, research)
    payload, options = calls[0]
    state = json.loads(payload['state'])
    assert len(payload['state']) <= 14000
    assert state['prematch_research']['official_xi'] == research['official_xi']
    assert state['prematch_context']['home']['team_id'] == 1
    assert 'x'*20000 == context['long_field']  # Source data was not modified.
    assert options['timeout'] == 25 and result['score'] == '1-0'


def test_small_state_and_score_options_are_preserved(enabled, monkeypatch):
    calls = fake_transport(monkeypatch, [response()])
    context, research = {'home': {'team_id': 1}}, {'official_xi': ['A']}
    ai_pool._cloudflare_clef('Home', 'Away', context, research)
    payload = calls[0][0]
    assert json.loads(payload['state']) == {'home_team': 'Home', 'away_team': 'Away',
        'prematch_context': context, 'prematch_research': research}
    assert payload['model'] == 'clef-omni'
    assert len(payload['questions']['score']['criteria']) == 25
    assert '4_4' in payload['questions']['score']['criteria']


@pytest.mark.parametrize('reason,kind', [(TimeoutError(), TimeoutError),
    (ConnectionRefusedError('private-url'), ConnectionError)])
def test_wrapped_network_failure_has_retryable_safe_category(enabled, monkeypatch, reason, kind):
    fake_transport(monkeypatch, [urllib.error.URLError(reason)])
    with pytest.raises(kind) as caught:
        ai_pool._cloudflare_clef('H', 'A', {}, {})
    assert 'private' not in str(caught.value)


@pytest.mark.parametrize('status', [401, 429, 503])
def test_http_error_keeps_status_and_retry_after(enabled, monkeypatch, status):
    error = urllib.error.HTTPError('private-url', status, 'private-message',
                                   {'Retry-After': '120'}, None)
    fake_transport(monkeypatch, [error])
    with pytest.raises(urllib.error.HTTPError) as caught:
        ai_pool._cloudflare_clef('H', 'A', {}, {})
    assert ai_pool.error_http_status(caught.value) == status
    assert ai_pool.retry_after_seconds(caught.value) == 120


@pytest.mark.parametrize('payload', ['not JSON', [], None])
def test_malformed_or_non_object_response_has_fixed_error(enabled, monkeypatch, payload):
    fake_transport(monkeypatch, [payload])
    with pytest.raises(ai_pool.OutputError, match='INVALID_JSON'):
        ai_pool._cloudflare_clef('H', 'A', {}, {})


def test_unsuccessful_envelope_is_not_misreported_as_invalid_json(enabled, monkeypatch):
    fake_transport(monkeypatch, [{'success': False, 'errors': [{'message': 'private-key'}]}])
    with pytest.raises(ai_pool.OutputError) as caught:
        ai_pool._cloudflare_clef('H', 'A', {}, {})
    assert ai_pool.safe_error(caught.value) == 'PROVIDER_UNAVAILABLE'
    assert 'private' not in str(caught.value)


@pytest.mark.parametrize('key', ['CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID'])
def test_missing_credentials_never_make_http_request(enabled, monkeypatch, key):
    monkeypatch.delenv(key)
    monkeypatch.setattr('urllib.request.urlopen', lambda *_a, **_k: pytest.fail('No credentials'))
    with pytest.raises(ai_pool.OutputError) as caught:
        ai_pool._cloudflare_clef('H', 'A', {}, {})
    assert ai_pool.safe_error(caught.value) == 'MISSING_API_KEY'


@pytest.mark.parametrize('failure', [urllib.error.URLError(TimeoutError()),
    urllib.error.URLError(ConnectionRefusedError()), 'not JSON'])
def test_common_retry_layer_recovers_and_persists_one_vote(enabled, monkeypatch, failure):
    calls = fake_transport(monkeypatch, [failure, response()])
    monkeypatch.setattr(ai_pool.time, 'sleep', lambda _: None)
    monkeypatch.setattr(ai_pool.random, 'uniform', lambda *_: 0)
    saved = []
    votes = ai_pool.run_ai_pool('H', 'A', {}, {}, {}, on_vote=saved.append)
    clef = next(v for v in votes if v.model == 'Cloudflare Clef-omni')
    assert clef.success and len(calls) == 2
    assert clef.result['score'] == '1-0'
    assert len([v for v in saved if v.model == clef.model]) == 1


def test_unclear_failure_envelope_is_not_blindly_retried(enabled, monkeypatch, capsys):
    calls = fake_transport(monkeypatch, [{'success': False, 'errors': [{'message': 'private-key'}]}])
    vote = next(v for v in ai_pool.run_ai_pool('H', 'A', {}, {}, {})
                if v.model == 'Cloudflare Clef-omni')
    assert not vote.success and vote.error == 'PROVIDER_UNAVAILABLE'
    assert len(calls) == 1 and 'private' not in capsys.readouterr().out
