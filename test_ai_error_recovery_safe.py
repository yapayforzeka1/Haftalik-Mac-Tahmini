"""Offline provider error classification; no real network or model requests."""
import pytest

import ai_pool


class HTTPFailure(Exception):
    def __init__(self, status, headers=None, body=None):
        super().__init__('do not log raw response')
        self.status_code = status
        self.headers = headers or {}
        self.body = body or {}


def test_persisted_retry_backoff_skips_provider_until_due(monkeypatch):
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert not ai_pool._retry_is_due(future)
    assert ai_pool._retry_is_due(past)
    assert ai_pool._retry_is_due(None)  # legacy failure records are recoverable


def test_gemini_unknown_429_without_retry_after_avoids_blind_retry(monkeypatch):
    attempts = []
    monkeypatch.setattr(ai_pool.time, 'sleep', lambda t: pytest.fail('unknown 429 should not sleep'))

    def fail():
        attempts.append(1)
        raise HTTPFailure(429)

    with pytest.raises(HTTPFailure):
        ai_pool._call_with_retry('Gemini 3.6 Flash', fail, max_retries=2)
    assert len(attempts) == 1


def test_gemini_503_bounded_retry_success(monkeypatch):
    attempts, waits = [], []
    monkeypatch.setattr(ai_pool.time, 'sleep', lambda t: waits.append(t))
    monkeypatch.setattr(ai_pool.random, 'uniform', lambda a, b: 0)

    def once():
        attempts.append(1)
        if len(attempts) == 1:
            raise HTTPFailure(503)
        return 'recovered'

    assert ai_pool._call_with_retry('Gemini 3.6 Flash', once, max_retries=2) == 'recovered'
    assert len(attempts) == 2 and waits == [10]


def test_gemini_does_not_retry_exhausted_billing_quota(monkeypatch):
    attempts = []
    monkeypatch.setattr(ai_pool.time, 'sleep', lambda t: pytest.fail('exhausted quota'))

    def fail():
        attempts.append(1)
        raise HTTPFailure(429, body={'error': {'message': 'daily quota exceeded'}})

    with pytest.raises(HTTPFailure):
        ai_pool._call_with_retry('Gemini 3.6 Flash', fail, max_retries=2)
    assert len(attempts) == 1


@pytest.mark.parametrize('tag,expected', [('1','HOME'), ('X','DRAW'), ('2','AWAY'),
                                          ('HOME_WIN','HOME'), ('AWAY_WIN','AWAY'),
                                          (' home ','HOME')])
def test_cohere_outcome_equivalents_without_score_inference(tag, expected):
    score = {'HOME':'2-1', 'DRAW':'1-1', 'AWAY':'0-1'}[expected]
    out = ai_pool._normalize({'outcome': tag, 'score': score, 'confidence': 67}, 'h','a')
    assert out['outcome'] == expected and out['score'] == score


@pytest.mark.parametrize('tag,score', [('AWAY_WIN','2-0'), ('1','0-1'),
                                       ('home maybe','2-1'), ('win','2-1')])
def test_ambiguous_or_contradictory_cohere_outcome_is_still_rejected(tag,score):
    with pytest.raises(ValueError):
        ai_pool._normalize({'outcome':tag,'score':score,'confidence':70}, 'h','a')


def test_cohere_validation_records_fixed_diagnostic_not_model_text(monkeypatch,capsys):
    monkeypatch.setenv('COHERE_API_KEY', 'private-token')
    for key in ('GEMINI_API_KEY','GROQ_API_KEY','CLOUDFLARE_API_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(ai_pool,'_cohere',lambda _: '{"outcome":"AWAY_WIN","score":"2-1","confidence":50}')
    votes = ai_pool.run_ai_pool('H', 'A', {}, {}, {})
    cohere = next(v for v in votes if v.model=='Cohere Command A+')
    assert not cohere.success and cohere.error == 'INVALID_PREDICTION'
    logged = capsys.readouterr().out
    assert 'AI VALIDATION | Cohere Command A+ | neden=OUTCOME_SCORE_CONFLICT' in logged
    assert 'private-token' not in logged
