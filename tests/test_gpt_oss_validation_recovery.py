import ai_pool


def test_validation_reasons_are_safe():
    check = ai_pool._prediction_validation_reason
    assert check({'outcome': 'AWAY', 'score': '2-1'}) == 'OUTCOME_SCORE_CONFLICT'
    assert check({'outcome': 'AWAY', 'score': '1-2', 'confidence': 55}) == 'OTHER_VALIDATION_ERROR'
    assert check({'outcome': 'AWAY', 'score': 'x-y'}) == 'INVALID_SCORE_FORMAT'
    assert check({'outcome': 'UNKNOWN', 'score': '1-2'}) == 'INVALID_OUTCOME'


def test_gpt_oss_retries_once_without_forging_vote(monkeypatch):
    monkeypatch.setattr(ai_pool.time, 'sleep', lambda _: None)
    monkeypatch.setenv('GROQ_API_KEY', 'fake')
    monkeypatch.setenv('CLEF_ENABLED', 'false')
    for key in ('GEMINI_API_KEY', 'COHERE_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    seen = []
    def groq(prompt, model):
        if model != ai_pool.GROQ_120B_MODEL:
            return '{"outcome":"HOME","score":"1-0","confidence":55}'
        seen.append(prompt)
        if len(seen) == 1:
            return '{"outcome":"AWAY","score":"2-1","confidence":55}'
        return '{"outcome":"AWAY","score":"1-2","confidence":55}'
    monkeypatch.setattr(ai_pool, '_groq', groq)
    votes = ai_pool.run_ai_pool('h', 'a', {}, {}, {})
    target = next(v for v in votes if v.model == 'Groq GPT-OSS 120B')
    assert target.success and target.result['score'] == '1-2'
    assert len(seen) == 2 and 'ZORUNLU SON KONTROL' in seen[1]


def test_gpt_oss_stays_failed_after_second_invalid_response(monkeypatch):
    monkeypatch.setattr(ai_pool.time, 'sleep', lambda _: None)
    monkeypatch.setenv('GROQ_API_KEY', 'fake')
    monkeypatch.setenv('CLEF_ENABLED', 'false')
    for key in ('GEMINI_API_KEY', 'COHERE_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    seen = []
    def groq(prompt, model):
        if model == ai_pool.GROQ_120B_MODEL:
            seen.append(prompt)
            return '{"outcome":"AWAY","score":"2-1","confidence":55}'
        return '{"outcome":"HOME","score":"1-0","confidence":55}'
    monkeypatch.setattr(ai_pool, '_groq', groq)
    votes = ai_pool.run_ai_pool('h', 'a', {}, {}, {})
    target = next(v for v in votes if v.model == 'Groq GPT-OSS 120B')
    assert not target.success and len(seen) == 2
