"""Qwen recovery uses fake providers and time; consumes no API quota."""
import json
import sys
from types import SimpleNamespace as NS

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


def run_qwen(monkeypatch, sequence, *, deadline=None, cached=None):
    monkeypatch.setenv('GROQ_API_KEY', 'private-key')
    monkeypatch.setenv('CLEF_ENABLED', 'false')
    for key in ('GEMINI_API_KEY', 'COHERE_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    calls = []
    def request(prompt, model):
        if model != ai_pool.GROQ_QWEN_MODEL: return GOOD
        calls.append(prompt)
        item = sequence[len(calls)-1]
        if isinstance(item, Exception): raise item
        return item
    monkeypatch.setattr(ai_pool, '_groq', request)
    votes = ai_pool.run_ai_pool('Home', 'Away', {}, {}, {}, deadline=deadline, cached=cached)
    return next(v for v in votes if v.model == ai_pool.QWEN_LABEL), calls


def test_conflict_recovers_without_rewriting_first_vote(monkeypatch, clock):
    vote, calls = run_qwen(monkeypatch, [CONFLICT, GOOD])
    assert vote.success and vote.result['outcome'] == 'HOME'
    assert vote.result['model_id'] == ai_pool.GROQ_QWEN_MODEL
    assert len(calls) == vote.request_attempts == 2
    assert 'ZORUNLU SON KONTROL' in calls[-1]


def test_repeated_conflict_has_safe_reason_and_no_invented_result(monkeypatch, clock, capsys):
    vote, calls = run_qwen(monkeypatch, [CONFLICT, CONFLICT])
    assert not vote.success and vote.result is None and len(calls) == 2
    assert vote.error == 'INVALID_PREDICTION'
    assert vote.error_detail == 'OUTCOME_SCORE_CONFLICT'
    out = capsys.readouterr().out
    assert CONFLICT not in out and 'private-key' not in out


def test_transient_then_conflict_gets_one_correction_within_three_calls(monkeypatch, clock):
    vote, calls = run_qwen(monkeypatch, [TimeoutError('private'), CONFLICT, GOOD])
    assert vote.success and len(calls) == vote.request_attempts == 3


@pytest.mark.parametrize('failure', ['not JSON', ai_pool.OutputError('EMPTY_RESPONSE'),
                                    ai_pool.OutputError('RESPONSE_TRUNCATED')])
def test_output_can_recover_once(monkeypatch, clock, failure):
    vote, calls = run_qwen(monkeypatch, [failure, GOOD])
    assert vote.success and len(calls) == 2


def test_failed_correction_never_requests_third_output(monkeypatch, clock):
    vote, calls = run_qwen(monkeypatch, [CONFLICT, TimeoutError('private')])
    assert not vote.success and vote.error == 'TIMEOUT' and len(calls) == 2


def test_deadline_blocks_correction(monkeypatch, clock):
    vote, calls = run_qwen(monkeypatch, [CONFLICT], deadline=35)
    assert not vote.success and len(calls) == 1 and clock.tick == 0


def test_three_timeouts_are_the_limit(monkeypatch, clock):
    vote, calls = run_qwen(monkeypatch, [TimeoutError('private')] * 3)
    assert not vote.success and len(calls) == vote.request_attempts == 3


@pytest.mark.parametrize('status', [401, 403, 404, 422])
def test_permanent_failure_is_not_retried(monkeypatch, clock, status):
    class Failure(Exception): status_code = status
    vote, calls = run_qwen(monkeypatch, [Failure('private')])
    assert not vote.success and len(calls) == 1


@pytest.mark.parametrize('headers,body,expected', [
    ({'Retry-After': '60'}, {}, 300),
    ({'Retry-After': '900'}, {}, 900),
    ({}, {'message': 'tokens per minute exceeded'}, 300),
    ({}, {'message': 'request rate limit'}, 300),
    ({}, {}, 3600),
    ({'Retry-After': '60'}, {'message': 'daily quota exceeded'}, 86400),
])
def test_persistent_cooldown_distinguishes_transient_and_unknown_quota(monkeypatch, headers, body, expected):
    error = Exception(); error.status_code = 429; error.headers = headers; error.body = body
    monkeypatch.setattr(ai_pool, '_retry_after_at', lambda seconds: seconds)
    assert ai_pool._persistent_retry_after(error, 'REQUEST', 'QUOTA_OR_RATE_LIMIT',
                                          provider=ai_pool.QWEN_LABEL) == expected


def test_long_retry_after_defers_without_early_request(monkeypatch, clock):
    class Failure(Exception):
        status_code = 429
        headers = {'Retry-After': '900'}
    vote, calls = run_qwen(monkeypatch, [Failure('private')])
    assert not vote.success and len(calls) == 1 and clock.tick == 0


@pytest.mark.parametrize('message', ['daily quota exceeded',
    'Rate limit reached on tokens per day (TPD)',
    'Rate limit reached on requests per day (RPD)'])
def test_known_daily_quota_does_not_retry(monkeypatch, clock, message):
    class Failure(Exception):
        status_code = 429
        body = {'message': message + ' private-key'}
    vote, calls = run_qwen(monkeypatch, [Failure()])
    assert not vote.success and len(calls) == 1 and clock.tick == 0
    assert vote.error_detail == 'QUOTA_EXHAUSTED'


@pytest.mark.parametrize('finish,expected', [('length', 'RESPONSE_TRUNCATED'),
    ('content_filter', 'RESPONSE_STOPPED'), ('tool_calls', 'RESPONSE_STOPPED')])
def test_truncated_or_stopped_sdk_output_is_rejected_even_with_valid_json(monkeypatch, finish, expected):
    monkeypatch.setenv('GROQ_API_KEY', 'private-key')
    payload = NS(choices=[NS(finish_reason=finish, message=NS(content=GOOD))])
    client = NS(chat=NS(completions=NS(create=lambda **_: payload)))
    monkeypatch.setitem(sys.modules, 'groq', NS(Groq=lambda **_: client))
    with pytest.raises(ai_pool.OutputError, match=expected):
        ai_pool._groq('prompt', ai_pool.GROQ_QWEN_MODEL)


def test_saved_success_is_not_generated_again_or_counted_as_new(monkeypatch, clock, capsys):
    name = ai_pool.QWEN_LABEL
    cached = {name: {'model': name, 'success': True, 'result': json.loads(GOOD),
                    'request_attempts': 2, 'elapsed_seconds': 12, 'queue_wait_seconds': 7}}
    vote, calls = run_qwen(monkeypatch, [], cached=cached)
    assert not calls and vote.request_attempts == 2 and vote.queue_wait_seconds == 7
    line = next(s for s in capsys.readouterr().out.splitlines()
                if s.startswith('AI TIMING | ' + name))
    assert 'current_attempts=0' in line and 'queue_seconds=0' in line
