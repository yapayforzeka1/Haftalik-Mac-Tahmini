"""No live requests: persistent limits, retries, clock rollover and isolation."""
from datetime import datetime, timedelta, timezone
import json

import pytest
import ai_pool
import runner
from gemini_budget import BudgetDeferred, GeminiRequestBudget
from storage import StateError, load_json


class Clock:
    def __init__(self):
        self.utc = datetime(2026, 11, 6, 18, tzinfo=timezone.utc)
        self.tick = 0.0
        self.waits = []

    def now(self): return self.utc
    def monotonic(self): return self.tick
    def sleep(self, seconds):
        self.waits.append(seconds)
        self.utc += timedelta(seconds=seconds)
        self.tick += seconds


def budget(tmp_path, clock, **kwargs):
    return GeminiRequestBudget(tmp_path / 'gemini.json', 'model', clock=clock.now,
                               monotonic=clock.monotonic, sleep=clock.sleep, **kwargs)


def test_sixth_request_waits_for_rolling_window(tmp_path):
    c = Clock(); b = budget(tmp_path, c)
    for _ in range(6): b.reserve()
    assert c.waits == [60.1]
    assert load_json(b.path, {})['models']['model']['attempts'] == 6


def test_minute_history_survives_new_instance(tmp_path):
    c = Clock(); a = budget(tmp_path, c)
    for _ in range(5): a.reserve()
    b = budget(tmp_path, c)
    with pytest.raises(BudgetDeferred) as err:
        b.reserve(deadline=50)
    assert err.value.category == 'LOCAL_MINUTE_BUDGET'
    assert not c.waits
    assert load_json(b.path, {})['models']['model']['attempts'] == 5


def test_daily_cap_survives_new_instance_and_does_not_wait(tmp_path):
    c = Clock(); a = budget(tmp_path, c, rpm=30)
    for _ in range(20): a.reserve()
    with pytest.raises(BudgetDeferred) as err:
        budget(tmp_path, c).reserve()
    assert err.value.category == 'LOCAL_DAILY_BUDGET'
    assert err.value.retry_after == '2026-11-07T08:00:00+00:00'
    assert not c.waits
    assert load_json(a.path, {})['models']['model']['attempts'] == 20


def test_pacific_midnight_resets_daily_count(tmp_path):
    c = Clock(); c.utc = datetime(2026, 11, 6, 7, 59, tzinfo=timezone.utc)
    b = budget(tmp_path, c, rpd=1)
    b.reserve()
    assert load_json(b.path, {})['models']['model']['day'] == '2026-11-05'
    c.sleep(61)
    b.reserve()
    state = load_json(b.path, {})['models']['model']
    assert state['day'] == '2026-11-06' and state['attempts'] == 1


def test_daily_reset_preserves_rolling_minute(tmp_path):
    c = Clock(); c.utc = datetime(2026, 11, 6, 7, 59, 59, tzinfo=timezone.utc)
    b = budget(tmp_path, c, rpm=1)
    b.reserve(); c.sleep(2)
    b.reserve()
    assert c.waits[-1] == pytest.approx(58.1)
    assert load_json(b.path, {})['models']['model']['attempts'] == 1


def test_insufficient_request_window_does_not_reserve(tmp_path):
    c = Clock(); b = budget(tmp_path, c)
    with pytest.raises(BudgetDeferred) as err: b.reserve(deadline=20)
    assert err.value.category == 'LOCAL_REQUEST_WINDOW'
    assert not b.path.exists()


@pytest.mark.parametrize('content', ['{broken', '{"schema":2,"models":{}}',
    '{"schema":1,"models":{"model":{"day":"bad","attempts":2,"recent":[]}}}',
    '{"schema":1,"models":{"model":{"day":"2026-11-06","attempts":-1,"recent":[]}}}'])
def test_corrupt_ledger_blocks_calls_without_replacing_file(tmp_path, content):
    c = Clock(); b = budget(tmp_path, c)
    b.path.write_text(content, encoding='utf-8')
    with pytest.raises(StateError): b.reserve()
    assert b.path.read_text(encoding='utf-8') == content


def only_gemini(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'fake')
    for name in ('GROQ_API_KEY', 'COHERE_API_KEY', 'CLOUDFLARE_API_TOKEN'):
        monkeypatch.delenv(name, raising=False)


def test_transient_retry_counts_both_requests(tmp_path, monkeypatch):
    only_gemini(monkeypatch)
    c = Clock(); b = budget(tmp_path, c)
    monkeypatch.setattr(ai_pool.time, 'sleep', c.sleep)
    monkeypatch.setattr(ai_pool.random, 'uniform', lambda *a: 0)
    calls = []
    class Failure(Exception): status_code = 503
    def request(prompt):
        calls.append(1)
        if len(calls) == 1: raise Failure()
        return '{"outcome":"HOME","score":"2-1","confidence":60}'
    monkeypatch.setattr(ai_pool, '_gemini', request)
    votes = ai_pool.run_ai_pool('H', 'A', {}, {}, {}, gemini_budget=b)
    assert votes[0].success and len(calls) == 2
    assert load_json(b.path, {})['models']['model']['attempts'] == 2


def test_last_failed_daily_request_does_not_allow_an_extra_retry(tmp_path, monkeypatch):
    only_gemini(monkeypatch)
    c = Clock(); b = budget(tmp_path, c, rpd=1)
    monkeypatch.setattr(ai_pool.time, 'sleep', c.sleep)
    calls = []
    class Failure(Exception): status_code = 503
    def request(prompt): calls.append(1); raise Failure()
    monkeypatch.setattr(ai_pool, '_gemini', request)
    votes = ai_pool.run_ai_pool('H', 'A', {}, {}, {}, gemini_budget=b)
    assert len(calls) == 1
    assert votes[0].error == 'LOCAL_DAILY_BUDGET'
    assert load_json(b.path, {})['models']['model']['attempts'] == 1


def test_cached_success_does_not_consume_budget(tmp_path, monkeypatch):
    only_gemini(monkeypatch)
    c = Clock(); b = budget(tmp_path, c)
    def forbidden(*a): pytest.fail('cached Gemini must not be called')
    monkeypatch.setattr(ai_pool, '_gemini', forbidden)
    cached = {'Gemini 3.6 Flash': {'model': 'Gemini 3.6 Flash', 'success': True,
              'result': {'outcome': 'HOME', 'score': '2-1', 'confidence': 60}}}
    votes = ai_pool.run_ai_pool('H', 'A', {}, {}, {}, cached=cached, gemini_budget=b)
    assert votes[0].success and not b.path.exists()


def test_exhausted_gemini_does_not_block_other_models(tmp_path, monkeypatch):
    only_gemini(monkeypatch); monkeypatch.setenv('GROQ_API_KEY', 'fake')
    c = Clock(); b = budget(tmp_path, c, rpd=1); b.reserve()
    def forbidden(*a): pytest.fail('Gemini budget exhausted')
    monkeypatch.setattr(ai_pool, '_gemini', forbidden)
    monkeypatch.setattr(ai_pool, '_groq', lambda *a:
                        '{"outcome":"HOME","score":"2-1","confidence":60}')
    votes = ai_pool.run_ai_pool('H', 'A', {}, {}, {}, gemini_budget=b)
    assert votes[0].error == 'LOCAL_DAILY_BUDGET'
    assert votes[0].error_stage == 'BUDGET'
    assert votes[1].success and votes[3].success


def test_reservation_exists_on_disk_before_provider_call(tmp_path, monkeypatch):
    only_gemini(monkeypatch)
    c = Clock(); b = budget(tmp_path, c)
    def request(prompt):
        assert load_json(b.path, {})['models']['model']['attempts'] == 1
        return '{"outcome":"HOME","score":"2-1","confidence":60}'
    monkeypatch.setattr(ai_pool, '_gemini', request)
    assert ai_pool.run_ai_pool('H', 'A', {}, {}, {}, gemini_budget=b)[0].success


def test_no_match_creates_no_usage_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setenv('TEST_MODE', 'false')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'fake')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'fake')
    monkeypatch.delenv('APPROVED_POLICY_FILE', raising=False)
    monkeypatch.setattr(runner, 'Telegram', lambda *a: object())
    class Football:
        def __init__(self, *a): pass
        def get_matches(self): return []
    monkeypatch.setattr(runner, 'CachedFootball', Football)
    assert runner.main() == 0
    assert not (tmp_path / 'data/gemini_usage.json').exists()


def test_workflow_persists_ledger_for_test_and_production():
    from pathlib import Path
    workflow = (Path(runner.__file__).parent / '.github/workflows/main.yml').read_text(encoding='utf-8')
    save_step = workflow.split('- name: Yarım kalan işlemler dâhil durumu kaydet', 1)[1]
    assert '!inputs.test_mode' not in save_step.split('run: |', 1)[0]
    assert 'git add data/gemini_usage.json' in save_step
    assert 'if [ "${{ inputs.test_mode }}" != "true" ]; then' in save_step


@pytest.mark.parametrize('status,headers,body,category,expected', [
    (503, {}, {}, 'PROVIDER_UNAVAILABLE', 300),
    (503, {'Retry-After': '900'}, {}, 'PROVIDER_UNAVAILABLE', 900),
    (429, {'Retry-After': '60'}, {}, 'QUOTA_OR_RATE_LIMIT', 300),
    (429, {'Retry-After': '600'}, {}, 'QUOTA_OR_RATE_LIMIT', 600),
    (429, {}, {}, 'QUOTA_OR_RATE_LIMIT', 3600),
    (429, {}, {'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}, 'QUOTA_OR_RATE_LIMIT', 300),
    (429, {}, {'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}, 'QUOTA_OR_RATE_LIMIT', 86400),
    (429, {'Retry-After': '60'}, {'message': 'daily quota exceeded'}, 'QUOTA_OR_RATE_LIMIT', 86400),
])
def test_persistent_gemini_cooldown_respects_server_and_unknown_quota(
        monkeypatch, status, headers, body, category, expected):
    class Failure(Exception): pass
    error = Failure(); error.status_code = status; error.headers = headers; error.body = body
    monkeypatch.setattr(ai_pool, '_retry_after_at', lambda seconds: seconds)
    assert ai_pool._persistent_retry_after(error, 'REQUEST', category,
                                          provider='Gemini 3.6 Flash') == expected


def test_quota_detail_is_saved_as_fixed_code(monkeypatch):
    only_gemini(monkeypatch)
    class Failure(Exception):
        status_code = 429
        body = {'message': 'daily quota exceeded'}
    def fail(*args): raise Failure()
    monkeypatch.setattr(ai_pool, '_gemini', fail)
    vote = ai_pool.run_ai_pool('H', 'A', {}, {}, {})[0]
    assert vote.error == 'QUOTA_OR_RATE_LIMIT'
    assert vote.error_detail == 'QUOTA_EXHAUSTED'
    assert ai_pool._cached_vote(vars(vote)).error_detail == 'QUOTA_EXHAUSTED'
