import copy
from dataclasses import asdict
from pathlib import Path

import pytest
import ai_pool
from gemini_budget import GeminiRequestBudget
from storage import load_json


@pytest.mark.parametrize('model,label', [
    ('gemini-3.5-flash-lite', 'Gemini 3.5 Flash-Lite'),
    ('gemini-3.6-flash', 'Gemini 3.6 Flash'),
    ('custom-version', 'Gemini (custom)'),
])
def test_model_label_matches_actual_provider_version(model, label):
    assert ai_pool.gemini_label(model) == label


def test_new_model_has_distinct_visible_short_label():
    from messages import short_model
    assert short_model('Gemini 3.5 Flash-Lite') == 'Gem 3.5L'
    assert short_model('Gemini 3.6 Flash') == 'Gemini'


def lite(monkeypatch):
    monkeypatch.setattr(ai_pool, 'GEMINI_MODEL', 'gemini-3.5-flash-lite')
    monkeypatch.setenv('GEMINI_API_KEY', 'fake')
    for name in ('GROQ_API_KEY', 'COHERE_API_KEY', 'CLOUDFLARE_API_TOKEN'):
        monkeypatch.delenv(name, raising=False)


def test_new_vote_has_distinct_name_and_id_without_mutating_old_cache(monkeypatch):
    lite(monkeypatch)
    cached = {'Gemini 3.6 Flash': {'model': 'Gemini 3.6 Flash', 'success': True,
              'result': {'score': '1-0', 'outcome': 'HOME', 'model_id': 'gemini-3.6-flash'}}}
    before = copy.deepcopy(cached); calls = []
    def request(prompt): calls.append(1); return '{"score":"2-1","outcome":"HOME","confidence":60}'
    monkeypatch.setattr(ai_pool, '_gemini', request)
    vote = ai_pool.run_ai_pool('H', 'A', {}, {}, {}, cached=cached)[0]
    assert vote.model == 'Gemini 3.5 Flash-Lite'
    assert vote.result['model_id'] == 'gemini-3.5-flash-lite'
    assert len(calls) == 1 and cached == before


def test_new_model_success_cache_does_not_call_provider(monkeypatch):
    lite(monkeypatch)
    cached = {'Gemini 3.5 Flash-Lite': {'model': 'Gemini 3.5 Flash-Lite', 'success': True,
              'result': {'score': '2-1', 'outcome': 'HOME', 'model_id': 'gemini-3.5-flash-lite'}}}
    monkeypatch.setattr(ai_pool, '_gemini', lambda *_: pytest.fail('cached success'))
    vote = ai_pool.run_ai_pool('H', 'A', {}, {}, {}, cached=cached)[0]
    assert vote.success and vote.model == 'Gemini 3.5 Flash-Lite'


def test_lite_uses_budget_and_bounded_retry(monkeypatch, tmp_path):
    lite(monkeypatch)
    monkeypatch.setattr(ai_pool.time, 'sleep', lambda *_: None)
    calls = []
    class Failure(Exception): status_code = 503
    def request(prompt):
        calls.append(1)
        if len(calls) == 1: raise Failure()
        return '{"score":"2-1","outcome":"HOME","confidence":60}'
    monkeypatch.setattr(ai_pool, '_gemini', request)
    budget = GeminiRequestBudget(tmp_path/'usage.json', ai_pool.GEMINI_MODEL)
    vote = ai_pool.run_ai_pool('H', 'A', {}, {}, {}, gemini_budget=budget)[0]
    assert vote.success and len(calls) == 2
    assert load_json(budget.path, {})['models']['gemini-3.5-flash-lite']['attempts'] == 2


def test_lite_failure_keeps_actual_model_name_and_five_minute_retry(monkeypatch):
    lite(monkeypatch)
    monkeypatch.setattr(ai_pool.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(ai_pool, '_retry_after_at', lambda seconds: str(seconds))
    class Failure(Exception): status_code = 503
    calls = []
    def request(prompt): calls.append(1); raise Failure()
    monkeypatch.setattr(ai_pool, '_gemini', request)
    vote = ai_pool.run_ai_pool('H', 'A', {}, {}, {})[0]
    assert not vote.success and vote.model == 'Gemini 3.5 Flash-Lite'
    assert vote.retry_after == '300' and len(calls) == 2


def test_production_default_changes_but_diagnostic_still_selects_explicitly():
    root = Path(ai_pool.__file__).parent
    source = (root/'ai_pool.py').read_text(encoding='utf-8')
    workflow = (root/'.github/workflows/main.yml').read_text(encoding='utf-8')
    assert 'os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")' in source
    assert "vars.GEMINI_MODEL || 'gemini-3.5-flash-lite'" in workflow
    assert 'inputs.diagnostic_model' not in workflow
