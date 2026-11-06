from datetime import datetime, timezone
from pathlib import Path
import json
import pytest

import ai_pool
import gemini_single_check as check
from gemini_budget import BudgetDeferred, GeminiRequestBudget
from storage import StateError, load_json


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'private-key')


class Budget:
    def __init__(self): self.count = 0
    def reserve(self, deadline=None): self.count += 1


def test_one_successful_sdk_call(enabled, capsys):
    budget = Budget(); calls = []
    def request(prompt):
        assert budget.count == 1
        calls.append(prompt)
        return '{"ok":true}'
    assert check.run(budget=budget, request=request) == 0
    assert len(calls) == 1 and budget.count == 1
    assert 'JSON_OK' in capsys.readouterr().out


@pytest.mark.parametrize('status,expected', [(503, 'PROVIDER_UNAVAILABLE'), (429, 'QUOTA_OR_RATE_LIMIT')])
def test_provider_failure_never_retries_or_leaks(enabled, capsys, status, expected):
    budget = Budget(); calls = []
    class Failure(Exception): status_code = status
    def request(prompt):
        calls.append(1)
        raise Failure('private-key private-response')
    assert check.run(budget=budget, request=request) == 1
    output = capsys.readouterr().out
    assert len(calls) == 1 and budget.count == 1
    assert expected in output and f'HTTP={status}' in output
    assert 'private-' not in output


def test_missing_key_does_not_reserve(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    budget = Budget()
    assert check.run(budget=budget, request=lambda *_: pytest.fail('No key')) == 2
    assert budget.count == 0


@pytest.mark.parametrize('error', [StateError('private-state'),
    BudgetDeferred('LOCAL_DAILY_BUDGET', datetime(2030, 1, 1, tzinfo=timezone.utc))])
def test_invalid_or_exhausted_ledger_never_calls_provider(enabled, error):
    class Blocked:
        def reserve(self, deadline=None): raise error
    assert check.run(budget=Blocked(), request=lambda *_: pytest.fail('blocked')) == 2


@pytest.mark.parametrize('raw', ['not JSON', '{"ok":false}'])
def test_invalid_output_is_failed_without_another_request(enabled, raw):
    budget = Budget(); calls = []
    def request(prompt): calls.append(1); return raw
    assert check.run(budget=budget, request=request) == 1
    assert len(calls) == 1 and budget.count == 1


def test_failed_request_is_persisted_in_real_ledger(enabled, tmp_path):
    path = tmp_path / 'ledger.json'
    budget = GeminiRequestBudget(path, 'test-model')
    def request(prompt): raise TimeoutError('private-key')
    assert check.run(budget=budget, request=request) == 1
    assert load_json(path, {})['models']['test-model']['attempts'] == 1


def test_diagnostic_workflow_is_manual_and_saves_only_usage_ledger():
    path = Path(check.__file__).parent / '.github/workflows/gemini-single-check.yml'
    text = path.read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in text and 'schedule:' not in text
    assert 'group: haftalik-mac-tahmini' in text
    assert 'git add data/gemini_usage.json' in text
    assert 'always()' in text
    assert 'TELEGRAM_BOT_TOKEN' not in text
    assert 'GROQ_API_KEY' not in text and 'COHERE_API_KEY' not in text
    assert 'python gemini_single_check.py' in text


def archived_record(tmp_path):
    record = {'match_id': '575394', 'home_team': 'Viking FK', 'away_team': 'Sabah FK',
              'context': {'home': {'form': 'pre-match data'}},
              'research': {'status': 'STRUCTURED_ONLY'}, 'history': {},
              'actual': {'secret_result': 'REAL_RESULT_MUST_NOT_BE_SENT'},
              'post_match_analysis': {'secret': 'POST_MATCH_MUST_NOT_BE_SENT'},
              'ai_votes': [{'secret': 'OLD_VOTE_MUST_NOT_BE_SENT'}]}
    path = tmp_path / 'predictions.json'
    path.write_text(json.dumps({'575394': record}), encoding='utf-8')
    return path, record


def test_archived_prediction_uses_real_template_without_current_result(enabled, tmp_path, capsys):
    path, record = archived_record(tmp_path); before = path.read_bytes()
    budget = Budget(); calls = []
    def request(prompt):
        calls.append(prompt)
        assert prompt == ai_pool.build_prompt(record['home_team'], record['away_team'],
                                               record['context'], record['research'], record['history'])
        assert 'MUST_NOT_BE_SENT' not in prompt
        return '{"outcome":"HOME","score":"2-1","confidence":60}'
    assert check.run(budget=budget, request=request, mode='archived_prediction',
                     match_id='575394', archive_path=path) == 0
    assert budget.count == 1 and len(calls) == 1
    assert path.read_bytes() == before
    assert 'PREDICTION_JSON_OK' in capsys.readouterr().out


@pytest.mark.parametrize('raw', ['not JSON', '{"ok":true}',
                               '{"outcome":"AWAY","score":"2-1","confidence":60}'])
def test_archived_output_requires_valid_score_and_outcome(enabled, tmp_path, raw):
    path, _ = archived_record(tmp_path); before = path.read_bytes()
    budget = Budget(); calls = []
    def request(prompt): calls.append(1); return raw
    assert check.run(budget=budget, request=request, mode='archived_prediction',
                     match_id='575394', archive_path=path) == 1
    assert budget.count == 1 and len(calls) == 1 and path.read_bytes() == before


@pytest.mark.parametrize('match_id', ['missing', '999', 'private-key'])
def test_missing_or_invalid_match_never_calls_ai(enabled, tmp_path, match_id):
    path, _ = archived_record(tmp_path); budget = Budget()
    assert check.run(budget=budget, request=lambda *_: pytest.fail('No record'),
                     mode='archived_prediction', match_id=match_id, archive_path=path) == 2
    assert budget.count == 0


def test_excluded_club_is_not_analysed(enabled, tmp_path):
    path, record = archived_record(tmp_path); record['home_team'] = 'Fenerbahçe SK'
    path.write_text(json.dumps({'575394': record}), encoding='utf-8')
    budget = Budget()
    assert check.run(budget=budget, request=lambda *_: pytest.fail('Excluded'),
                     mode='archived_prediction', match_id='575394', archive_path=path) == 2
    assert budget.count == 0


def test_invalid_mode_never_calls_ai(enabled):
    budget = Budget()
    assert check.run(budget=budget, request=lambda *_: pytest.fail('Invalid mode'), mode='unknown') == 2
    assert budget.count == 0


def test_empty_archived_context_is_rejected_when_not_an_object(enabled, tmp_path):
    path, record = archived_record(tmp_path); record['context'] = None
    path.write_text(json.dumps({'575394': record}), encoding='utf-8')
    budget = Budget()
    assert check.run(budget=budget, request=lambda *_: pytest.fail('Invalid inputs'),
                     mode='archived_prediction', match_id='575394', archive_path=path) == 2
    assert budget.count == 0


def test_alternate_model_ledger_does_not_reset_original_model(enabled, tmp_path, monkeypatch, capsys):
    from storage import save_json
    ledger = tmp_path / 'data/gemini_usage.json'
    original = {'day': '2026-11-06', 'attempts': 4, 'recent': []}
    save_json(ledger, {'schema': 1, 'models': {'gemini-3.6-flash': original}})
    monkeypatch.setattr(check, '__file__', str(tmp_path / 'gemini_single_check.py'))
    monkeypatch.setattr(ai_pool, 'GEMINI_MODEL', 'gemini-3.5-flash-lite')
    calls = []
    def request(prompt): calls.append(1); return '{"ok":true}'
    assert check.run(request=request) == 0
    models = load_json(ledger, {})['models']
    assert len(calls) == 1
    assert models['gemini-3.6-flash'] == original
    assert models['gemini-3.5-flash-lite']['attempts'] == 1
    assert 'model=gemini-3.5-flash-lite' in capsys.readouterr().out


def test_diagnostic_model_choice_is_not_a_production_setting():
    root = Path(check.__file__).parent
    diagnostic = (root / '.github/workflows/gemini-single-check.yml').read_text(encoding='utf-8')
    production = (root / '.github/workflows/main.yml').read_text(encoding='utf-8')
    assert 'gemini-3.5-flash-lite' in diagnostic
    assert "GEMINI_MODEL: ${{ inputs.diagnostic_model || vars.GEMINI_MODEL || 'gemini-3.6-flash' }}" in diagnostic
    assert 'inputs.diagnostic_model' not in production
    assert "GEMINI_MODEL: ${{ vars.GEMINI_MODEL || 'gemini-3.5-flash-lite' }}" in production
