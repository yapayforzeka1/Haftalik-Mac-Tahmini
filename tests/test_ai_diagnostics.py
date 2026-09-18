import pytest

import ai_pool


class ProviderError(Exception):
    def __init__(self, status):
        self.status_code = status
        super().__init__('private-token private-prompt private-response')


@pytest.mark.parametrize('status,expected', [(429,'QUOTA_OR_RATE_LIMIT'), (401,'AUTH_ERROR'),
    (403,'AUTH_ERROR'), (404,'MODEL_OR_ENDPOINT_NOT_FOUND'), (503,'PROVIDER_UNAVAILABLE'),
    (400,'INVALID_REQUEST')])
def test_http_categories(status,expected):
    assert ai_pool.safe_error(ProviderError(status)) == expected


def test_sdk_argument_error_is_identifiable_without_raw_message():
    assert ai_pool.safe_error(TypeError('private-token unexpected argument')) == 'SDK_ARGUMENT_ERROR'


def test_all_models_final_diagnostics_without_sensitive_content(monkeypatch,capsys):
    for name in ('GEMINI_API_KEY','MISTRAL_API_KEY','GROQ_API_KEY','COHERE_API_KEY'):
        monkeypatch.setenv(name,'private-token')
    def fail(prompt):
        raise ProviderError(429)
    monkeypatch.setattr(ai_pool,'_gemini',fail)
    monkeypatch.setattr(ai_pool,'_mistral',lambda p:'private-response')
    monkeypatch.setattr(ai_pool,'_cohere',lambda p:'{"outcome":"AWAY","score":"2-0"}')
    monkeypatch.setattr(ai_pool,'_groq',lambda p,m:'{"outcome":"HOME","score":"2-0","confidence":60}')
    votes=ai_pool.run_ai_pool('h','a',{}, {}, {})
    output=capsys.readouterr().out
    assert output.count('AI | ')==5 and 'AI TOPLAM | 2/5 basarili' in output
    assert 'asama=REQUEST | neden=QUOTA_OR_RATE_LIMIT | HTTP=429' in output
    assert 'asama=PARSE | neden=INVALID_JSON' in output
    assert 'asama=VALIDATE | neden=INVALID_PREDICTION' in output
    assert 'private-' not in output
    assert sum(v.success for v in votes)==2


def test_missing_keys_logged_without_calling_providers(monkeypatch,capsys):
    for name in ('GEMINI_API_KEY','MISTRAL_API_KEY','GROQ_API_KEY','COHERE_API_KEY'):
        monkeypatch.delenv(name,raising=False)
    ai_pool.run_ai_pool('h','a',{}, {}, {})
    output=capsys.readouterr().out
    assert output.count('neden=MISSING_API_KEY')==5
    assert 'AI TOPLAM | 0/5 basarili' in output


def test_cached_error_text_is_not_printed(capsys):
    names=['Gemini 3.6 Flash','Mistral Small Latest','Groq Qwen 3.6 27B','Cohere Command A+','Groq GPT-OSS 120B']
    cached={name:{'model':name,'success':False,'error':'private-token'} for name in names}
    ai_pool.run_ai_pool('h','a',{}, {}, {},cached=cached)
    output=capsys.readouterr().out
    assert 'private-token' not in output
    assert output.count('asama=CACHE')==5
