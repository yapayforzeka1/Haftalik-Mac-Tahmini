"""Independent OpenRouter free-model diagnostic. No paid-model fallback."""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = 'https://openrouter.ai/api/v1'
KEY = os.environ.get('OPENROUTER_API_KEY', '').strip()
PREFERRED = os.environ.get('OPENROUTER_FREE_MODEL', '').strip()


def request(path, *, payload=None):
    headers = {'Accept': 'application/json', 'User-Agent': 'champions-league-free-diagnostic/1.0'}
    if KEY:
        headers['Authorization'] = f'Bearer {KEY}'
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(BASE + path, headers=headers,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 method='POST' if payload is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as exc:
        try:
            body = json.load(exc)
        except (ValueError, UnicodeError):
            body = {}
        return exc.code, body


def error_message(data):
    error = data.get('error', {}) if isinstance(data, dict) else {}
    message = error.get('message', 'Unknown error') if isinstance(error, dict) else str(error)
    # Never print raw provider errors; they can contain request details.
    return str(message).replace('\n', ' ')[:240]


def main():
    if not KEY:
        print('DIAG | OPENROUTER | FAIL | OPENROUTER_API_KEY missing')
        return 1
    try:
        status, catalog = request('/models')
        if status != 200:
            print(f'DIAG | OPENROUTER/catalog | FAIL | HTTP={status} | {error_message(catalog)}')
            return 1
        models = catalog.get('data', [])
        free = {m['id']: m for m in models if isinstance(m, dict) and
                isinstance(m.get('id'), str) and m['id'].endswith(':free') and
                str(m.get('pricing', {}).get('prompt', 'unknown')) in ('0', '0.0', '0.000000') and
                str(m.get('pricing', {}).get('completion', 'unknown')) in ('0', '0.0', '0.000000')}
        print(f'DIAG | OPENROUTER/catalog | OK | zero-priced :free models={len(free)}')
        if PREFERRED:
            if PREFERRED not in free:
                print('DIAG | OPENROUTER/model | FAIL | configured model is not listed as free')
                return 1
            model = PREFERRED
        else:
            priorities = ('deepseek/', 'meta-llama/', 'mistralai/', 'google/', 'qwen/')
            ranked = sorted(free, key=lambda mid: (next((i for i, prefix in enumerate(priorities)
                                                       if mid.startswith(prefix)), len(priorities)), mid))
            if not ranked:
                print('DIAG | OPENROUTER/model | FAIL | no eligible free models')
                return 1
            model = ranked[0]
        print(f'DIAG | OPENROUTER/model | selected={model}')
        status, response = request('/chat/completions', payload={
            'model': model,
            'messages': [{'role': 'user', 'content': 'Reply with exactly: OK'}],
            'max_tokens': 24,
            'temperature': 0,
            'provider': {'allow_fallbacks': False, 'require_parameters': True},
        })
        if status != 200:
            print(f'DIAG | OPENROUTER/chat | FAIL | HTTP={status} | {error_message(response)}')
            return 1
        choices = response.get('choices', [])
        content = choices[0].get('message', {}).get('content') if choices else None
        if not isinstance(content, str) or not content.strip():
            print('DIAG | OPENROUTER/chat | FAIL | HTTP=200 but no text response')
            return 1
        print('DIAG | OPENROUTER/chat | OK | HTTP=200 | nonempty response')
        print('DIAG | COMPLETE | API connectivity only; prediction accuracy not measured')
        return 0
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        print(f'DIAG | OPENROUTER | FAIL | {type(exc).__name__}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
