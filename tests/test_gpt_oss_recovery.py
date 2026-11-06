"""GPT recovery and Groq response checks; fake SDK, fake clock, no live quota."""
from dataclasses import asdict
from types import SimpleNamespace as NS
import sys
import json

import pytest
import ai_pool
from storage import load_json, save_json


NAME = 'Groq GPT-OSS 120B'
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


def enable(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'private-key')
    monkeypatch.setenv('CLEF_ENABLED', 'false')
    for key in ('GEMINI_API_KEY', 'COHERE_API_KEY'):
        monkeypatch.delenv(key, raising=False)


def run_gpt(monkeypatch, sequence, *, deadline=None, cached=None):
    enable(monkeypatch)
    calls = []
    def request(prompt, model):
        if model != ai_pool.GROQ_120B_MODEL: return GOOD
        calls.append(prompt)
        item = sequence[len(calls)-1]
        if isinstance(item, Exception): raise item
        return item
    monkeypatch.setattr(ai_pool, '_groq', request)
    votes = ai_pool.run_ai_pool('Home', 'Away', {}, {}, {}, deadline=deadline, cached=cached)
    return next(v for v in votes if v.model == NAME), calls


def test_invalid_prediction_is_not_mislabelled_json():
    assert ai_pool.safe_error(ai_pool.OutputError('GPT_OSS_INVALID_PREDICTION')) == 'INVALID_PREDICTION'


def test_two_conflicting_answers_stay_failed_with_safe_detail(monkeypatch, clock, capsys):
    vote, calls = run_gpt(monkeypatch, [CONFLICT, CONFLICT])
    assert len(calls) == 2 and vote.request_attempts == 2
    assert not vote.success and vote.result is None
    assert vote.error == 'INVALID_PREDICTION' and vote.error_detail == 'OUTCOME_SCORE_CONFLICT'
    output = capsys.readouterr().out
    assert 'private-' not in output and CONFLICT not in output


def test_transport_then_invalid_then_corrective_success(monkeypatch, clock):
    vote, calls = run_gpt(monkeypatch, [TimeoutError('hidden'), CONFLICT, GOOD])
    assert vote.success and vote.result['score'] == '2-1'
    assert len(calls) == vote.request_attempts == 3
    assert vote.elapsed_seconds == 30
    assert 'ZORUNLU SON KONTROL' in calls[-1]


def test_corrective_timeout_never_starts_third_request(monkeypatch, clock):
    vote, calls = run_gpt(monkeypatch, [CONFLICT, TimeoutError('hidden')])
    assert not vote.success and vote.error == 'TIMEOUT'
    assert len(calls) == 2


@pytest.mark.parametrize('failure', ['not JSON', ai_pool.OutputError('RESPONSE_TRUNCATED'),
                                   ai_pool.OutputError('EMPTY_RESPONSE')])
def test_output_failure_can_recover_once(monkeypatch, clock, failure):
    vote, calls = run_gpt(monkeypatch, [failure, GOOD])
    assert vote.success and len(calls) == 2


def test_repeated_truncation_is_distinct_from_json_error(monkeypatch, clock):
    vote, calls = run_gpt(monkeypatch, [ai_pool.OutputError('RESPONSE_TRUNCATED')] * 2)
    assert not vote.success and len(calls) == 2
    assert vote.error == 'RESPONSE_TRUNCATED' and vote.error_detail == 'OUTPUT_TOKEN_LIMIT'


def test_correction_does_not_start_past_deadline(monkeypatch, clock):
    vote, calls = run_gpt(monkeypatch, [TimeoutError('hidden'), CONFLICT], deadline=60)
    assert not vote.success and len(calls) == 2
    assert clock.tick == 10


def test_transient_timeouts_remain_capped_at_three(monkeypatch, clock):
    vote, calls = run_gpt(monkeypatch, [TimeoutError('hidden')] * 3)
    assert not vote.success and len(calls) == 3
    assert vote.request_attempts == 3 and vote.elapsed_seconds == 30


@pytest.mark.parametrize('status', [401, 403, 404, 422])
def test_permanent_errors_are_not_retried(monkeypatch, clock, status):
    class Failure(Exception): status_code = status
    vote, calls = run_gpt(monkeypatch, [Failure('private-key')])
    assert not vote.success and len(calls) == 1


def test_provider_retry_after_is_never_shortened(monkeypatch, clock):
    class Failure(Exception):
        status_code = 429
        headers = {'Retry-After': '120'}
    vote, calls = run_gpt(monkeypatch, [Failure('hidden')])
    assert not vote.success and len(calls) == 1 and clock.tick == 0


def fake_sdk(monkeypatch, response):
    calls, clients = [], []
    def create(**kwargs): calls.append(kwargs); return response
    client = NS(chat=NS(completions=NS(create=create)))
    def constructor(**kwargs): clients.append(kwargs); return client
    monkeypatch.setitem(sys.modules, 'groq', NS(Groq=constructor))
    monkeypatch.setenv('GROQ_API_KEY', 'private-key')
    return calls, clients


def response(finish='stop', content=GOOD):
    return NS(choices=[NS(finish_reason=finish, message=NS(content=content))])


def test_gpt_sdk_parameters_unchanged(monkeypatch):
    calls, clients = fake_sdk(monkeypatch, response())
    assert ai_pool._groq('prompt', ai_pool.GROQ_120B_MODEL) == GOOD
    assert clients == [{'api_key': 'private-key', 'timeout': 25, 'max_retries': 0}]
    assert calls[0]['model'] == ai_pool.GROQ_120B_MODEL
    assert calls[0]['max_completion_tokens'] == 1100
    assert calls[0]['reasoning_effort'] == 'low'
    assert calls[0]['response_format'] == {'type': 'json_object'}


@pytest.mark.parametrize('content', [GOOD, '', '{"score":'])
def test_length_finish_is_rejected_even_if_content_looks_valid(monkeypatch, content):
    fake_sdk(monkeypatch, response('length', content))
    with pytest.raises(ai_pool.OutputError, match='RESPONSE_TRUNCATED'):
        ai_pool._groq('prompt', ai_pool.GROQ_120B_MODEL)


@pytest.mark.parametrize('reason', ['content_filter', 'tool_calls', 'function_call', 'error'])
def test_stopped_generation_is_not_accepted(monkeypatch, reason):
    fake_sdk(monkeypatch, response(reason))
    with pytest.raises(ai_pool.OutputError, match='RESPONSE_STOPPED'):
        ai_pool._groq('prompt', ai_pool.GROQ_120B_MODEL)


@pytest.mark.parametrize('payload', [NS(choices=[]), response(content=None), response(content='   ')])
def test_empty_sdk_response_has_fixed_category(monkeypatch, payload):
    fake_sdk(monkeypatch, payload)
    with pytest.raises(ai_pool.OutputError, match='EMPTY_RESPONSE'):
        ai_pool._groq('prompt', ai_pool.GROQ_120B_MODEL)


def test_qwen_parameters_are_preserved(monkeypatch):
    calls, _ = fake_sdk(monkeypatch, response())
    assert ai_pool._groq('prompt', ai_pool.GROQ_QWEN_MODEL) == GOOD
    assert calls[0]['reasoning_effort'] == 'none'
    assert calls[0]['max_completion_tokens'] == 1100


def test_cache_does_not_call_gpt_or_claim_new_attempts(monkeypatch, clock, capsys):
    saved = {NAME: {'model': NAME, 'success': True, 'result': json.loads(GOOD),
             'request_attempts': 2, 'elapsed_seconds': 12.0, 'queue_wait_seconds': 7.0}}
    vote, calls = run_gpt(monkeypatch, [], cached=saved)
    assert not calls and vote.request_attempts == 2 and vote.queue_wait_seconds == 7.0
    out = capsys.readouterr().out
    line = next(s for s in out.splitlines() if s.startswith('AI TIMING | Groq GPT-OSS'))
    assert 'current_attempts=0' in line and 'queue_seconds=0' in line


def synchronous_pool(monkeypatch):
    class Future:
        def __init__(self, value): self.value = value
        def result(self): return self.value
    class Executor:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def submit(self, fn, *args): return Future(fn(*args))
    monkeypatch.setattr(ai_pool, 'ThreadPoolExecutor', Executor)
    monkeypatch.setattr(ai_pool, 'as_completed', lambda jobs: list(jobs))


def test_groq_lock_wait_and_request_time_are_distinct(monkeypatch, clock, tmp_path):
    enable(monkeypatch); synchronous_pool(monkeypatch)
    class Lock:
        count = 0
        def __enter__(self):
            self.count += 1
            if self.count == 2: clock.sleep(7)
        def __exit__(self, *args): pass
    monkeypatch.setattr(ai_pool, 'threading', NS(Lock=Lock))
    def request(prompt, model): clock.sleep(2); return GOOD
    monkeypatch.setattr(ai_pool, '_groq', request)
    votes = ai_pool.run_ai_pool('H', 'A', {}, {}, {})
    target = next(v for v in votes if v.model == NAME)
    assert target.success and target.queue_wait_seconds == 7
    assert target.elapsed_seconds == 2 and target.request_attempts == 1
    path = tmp_path/'saved.json'; save_json(path, asdict(target))
    restored = ai_pool._cached_vote(load_json(path, {}))
    assert restored.queue_wait_seconds == 7 and restored.elapsed_seconds == 2


def test_deadline_after_groq_lock_wait_makes_no_gpt_request(monkeypatch, clock):
    enable(monkeypatch); synchronous_pool(monkeypatch)
    class Lock:
        count = 0
        def __enter__(self):
            self.count += 1
            if self.count == 2: clock.sleep(70)
        def __exit__(self, *args): pass
    monkeypatch.setattr(ai_pool, 'threading', NS(Lock=Lock))
    called = []
    def request(prompt, model): called.append(model); return GOOD
    monkeypatch.setattr(ai_pool, '_groq', request)
    target = next(v for v in ai_pool.run_ai_pool('H', 'A', {}, {}, {}, deadline=90) if v.model == NAME)
    assert not target.success and target.error == 'TIME_BUDGET'
    assert called == [ai_pool.GROQ_QWEN_MODEL]
    assert target.queue_wait_seconds == 70 and target.request_attempts == 0
