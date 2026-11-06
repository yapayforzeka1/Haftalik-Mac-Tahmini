from datetime import datetime, timezone
from pathlib import Path
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
