"""Cohere recovery tests use fake calls and a virtual clock; no live quota."""
import json
from datetime import datetime, timezone
from dataclasses import asdict

import pytest
import ai_pool


GOOD = '{"outcome":"HOME","score":"2-1","confidence":60}'
CONFLICT = '{"outcome":"AWAY","score":"2-1","confidence":60}'


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        tick = 0.0
        def sleep(self, seconds): self.tick += seconds
        def now(self): return self.tick
    c = Clock()
    monkeypatch.setattr(ai_pool.time, 'monotonic', c.now)
    monkeypatch.setattr(ai_pool.time, 'sleep', c.sleep)
    monkeypatch.setattr(ai_pool.random, 'uniform', lambda *_: 0)
    return c


def run_cohere(monkeypatch, sequence, *, deadline=None, cached=None):
    monkeypatch.setenv('COHERE_API_KEY', 'private-key')
    for key in ('GEMINI_API_KEY', 'GROQ_API_KEY', 'CLOUDFLARE_API_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    calls = []
    def request(prompt):
        calls.append(prompt)
        item = sequence[len(calls) - 1]
        if isinstance(item, Exception): raise item
        return item
    monkeypatch.setattr(ai_pool, '_cohere', request)
    votes = ai_pool.run_ai_pool('Home', 'Away', {}, {}, {}, deadline=deadline, cached=cached)
    return next(v for v in votes if v.model == 'Cohere Command A+'), calls


def test_conflicting_first_answer_gets_one_corrective_request(monkeypatch, clock):
    vote, calls = run_cohere(monkeypatch, [CONFLICT, GOOD])
    assert vote.success and vote.result['score'] == '2-1'
    assert len(calls) == vote.request_attempts == 2
    assert 'ZORUNLU SON KONTROL' not in calls[0]
    assert 'ZORUNLU SON KONTROL' in calls[1]
    assert vote.elapsed_seconds == 10


def test_two_invalid_answers_remain_failed_not_repaired_by_code(monkeypatch, clock, capsys):
    vote, calls = run_cohere(monkeypatch, [CONFLICT, CONFLICT])
    assert not vote.success and vote.result is None and len(calls) == 2
    assert vote.error == 'INVALID_PREDICTION'
    assert vote.error_detail == 'OUTCOME_SCORE_CONFLICT'
    output = capsys.readouterr().out
    assert 'private-key' not in output and CONFLICT not in output
    assert 'current_attempts=2' in output


def test_corrective_request_timeout_does_not_trigger_third_generation(monkeypatch, clock):
    vote, calls = run_cohere(monkeypatch, [CONFLICT, TimeoutError('private-key')])
    assert not vote.success and vote.error == 'TIMEOUT'
    assert len(calls) == 2 and vote.request_attempts == 2


def test_transport_retry_can_be_followed_by_one_correction_within_total_cap(monkeypatch, clock):
    vote, calls = run_cohere(monkeypatch, [TimeoutError('hidden'), CONFLICT, GOOD])
    assert vote.success and len(calls) == 3 and vote.request_attempts == 3


def test_persistent_timeout_still_has_bounded_three_attempts(monkeypatch, clock):
    vote, calls = run_cohere(monkeypatch, [TimeoutError('hidden')] * 3)
    assert not vote.success and len(calls) == 3
    assert vote.error == 'TIMEOUT' and vote.elapsed_seconds == 30


def test_empty_httpx_timeout_message_is_still_classified():
    import httpx
    assert ai_pool.safe_error(httpx.ReadTimeout('')) == 'TIMEOUT'
    assert ai_pool.safe_error(TimeoutError('')) == 'TIMEOUT'


def test_no_late_retry_when_request_window_is_insufficient(monkeypatch, clock):
    vote, calls = run_cohere(monkeypatch, [CONFLICT], deadline=35)
    assert not vote.success and len(calls) == 1
    assert clock.tick == 0


def test_25_second_timeouts_do_not_start_third_request_after_budget(monkeypatch, clock):
    monkeypatch.setenv('COHERE_API_KEY', 'private-key')
    for key in ('GEMINI_API_KEY', 'GROQ_API_KEY', 'CLOUDFLARE_API_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    calls = []
    def request(prompt):
        calls.append(1); clock.sleep(25); raise TimeoutError('hidden')
    monkeypatch.setattr(ai_pool, '_cohere', request)
    vote = next(v for v in ai_pool.run_ai_pool('H', 'A', {}, {}, {}, deadline=100)
                if v.model == 'Cohere Command A+')
    assert len(calls) == 2 and clock.tick == 60
    assert vote.request_attempts == 2 and vote.elapsed_seconds == 60


@pytest.mark.parametrize('tag,score,outcome', [
    ('DEPLASMAN', '0-2', 'AWAY'), ('Ev Sahibi', '2-0', 'HOME'),
    ('EV SAHİBİ', '2-1', 'HOME'), ('BERABERLİK', '1-1', 'DRAW'),
    ('beraberlik', '0-0', 'DRAW'),
])
def test_unambiguous_turkish_labels_are_only_translated(tag, score, outcome):
    result = ai_pool._normalize({'outcome': tag, 'score': score, 'confidence': 60}, 'H', 'A')
    assert result['outcome'] == outcome and result['score'] == score


@pytest.mark.parametrize('tag,score', [('DEPLASMAN','2-0'), ('EV SAHİBİ','0-1'), ('BERABERLİK','2-1')])
def test_translation_never_overrides_a_conflicting_score(tag, score):
    with pytest.raises(ValueError):
        ai_pool._normalize({'outcome':tag,'score':score,'confidence':60},'H','A')


@pytest.mark.parametrize('failure', ['not JSON', ai_pool.OutputError('RESPONSE_TRUNCATED')])
def test_json_or_truncation_can_recover_once(monkeypatch, clock, failure):
    vote, calls = run_cohere(monkeypatch, [failure, GOOD])
    assert vote.success and len(calls) == 2


@pytest.mark.parametrize('status', [401, 403, 404, 422])
def test_permanent_provider_errors_do_not_repeat(monkeypatch, clock, status):
    class Failure(Exception): status_code = status
    vote, calls = run_cohere(monkeypatch, [Failure('hidden')])
    assert not vote.success and len(calls) == 1


def test_success_cache_preserves_metrics_and_makes_no_new_call(monkeypatch, clock, capsys):
    saved = {'Cohere Command A+': {'model':'Cohere Command A+','success':True,
             'result':json.loads(GOOD), 'request_attempts':2,'elapsed_seconds':12.5}}
    vote, calls = run_cohere(monkeypatch, [], cached=saved)
    assert not calls and vote.request_attempts == 2 and vote.elapsed_seconds == 12.5
    assert 'current_attempts=0' in capsys.readouterr().out
    assert ai_pool._cached_vote(asdict(vote)).request_attempts == 2


@pytest.mark.parametrize('category,headers,expected', [
    ('TIMEOUT', {}, 300), ('INVALID_PREDICTION', {}, 300),
    ('RESPONSE_TRUNCATED', {}, 300), ('TIMEOUT', {'Retry-After':'900'}, 900),
])
def test_next_trigger_cooldown_never_shortens_server_wait(monkeypatch, category, headers, expected):
    class Failure(Exception): pass
    error=Failure(); error.headers=headers
    monkeypatch.setattr(ai_pool,'_retry_after_at',lambda seconds:seconds)
    assert ai_pool._persistent_retry_after(error,'VALIDATE',category,provider='Cohere Command A+') == expected
