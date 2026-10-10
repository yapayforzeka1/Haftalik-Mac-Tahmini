"""Independent OpenRouter free-model diagnostic. No paid-model fallback."""
import json
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

BASE = 'https://openrouter.ai/api/v1'
KEY = os.environ.get('OPENROUTER_API_KEY', '').strip()
PREFERRED = os.environ.get('OPENROUTER_FREE_MODEL', '').strip()


def request(path, *, payload=None):
    headers = {'Accept': 'application/json', 'User-Agent': 'champions-league-free-diagnostic/2.0'}
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
            data = json.load(exc)
        except (ValueError, UnicodeError):
            data = {}
        return exc.code, data


def safe_error(data):
    """Classify errors without emitting untrusted provider text or credentials."""
    error = data.get('error') if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return 'category=unstructured_error'
    code = error.get('code')
    code = str(code) if isinstance(code, (int, str)) else 'unknown'
    if not code.replace('-', '').replace('_', '').isalnum() or len(code) > 32:
        code = 'unknown'
    message = str(error.get('message', '')).lower()
    metadata = error.get('metadata')
    provider_message = ''
    if isinstance(metadata, dict):
        provider_message = str(metadata.get('raw', '')).lower()[:500]
    combined = (message + ' ' + provider_message)[:1500]
    if any(term in combined for term in ('credit limit', 'insufficient credit', 'insufficient balance', 'not enough credits')):
        category = 'credit_or_key_limit'
    elif any(term in combined for term in ('rate limit', 'too many requests', 'quota', '429')):
        category = 'rate_or_quota_limit'
    elif any(term in combined for term in ('provider', 'upstream', 'overloaded', 'capacity')):
        category = 'provider_unavailable'
    elif any(term in combined for term in ('unauthorized', 'invalid api key', 'authentication')):
        category = 'authentication'
    elif any(term in combined for term in ('forbidden', 'permission')):
        category = 'permission'
    else:
        category = 'unknown'
    return f'error_code={code} | category={category}'


def zero_price(value):
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def eligible_models(catalog):
    models = catalog.get('data', []) if isinstance(catalog, dict) else []
    result = {}
    for model in models:
        if not isinstance(model, dict):
            continue
        mid = model.get('id')
        pricing = model.get('pricing')
        if not isinstance(mid, str) or not mid.endswith(':free') or not isinstance(pricing, dict):
            continue
        if zero_price(pricing.get('prompt')) and zero_price(pricing.get('completion')):
            result[mid] = model
    return result


def main():
    if not KEY:
        print('DIAG | OPENROUTER | FAIL | OPENROUTER_API_KEY missing')
        return 1
    try:
        status, catalog = request('/models')
        if status != 200:
            print(f'DIAG | OPENROUTER/catalog | FAIL | HTTP={status} | {safe_error(catalog)}')
            return 1
        free = eligible_models(catalog)
        print(f'DIAG | OPENROUTER/catalog | OK | zero-priced :free models={len(free)}')
        if PREFERRED:
            if PREFERRED not in free:
                print('DIAG | OPENROUTER/model | FAIL | configured model is not listed as free')
                return 1
            candidates = [PREFERRED]
        else:
            priorities = ('deepseek/', 'meta-llama/', 'mistralai/', 'google/', 'qwen/')
            ranked = sorted(free, key=lambda mid: (next((i for i, prefix in enumerate(priorities)
                                                        if mid.startswith(prefix)), len(priorities)), mid))
            candidates = ranked[:2]
        if not candidates:
            print('DIAG | OPENROUTER/model | FAIL | no eligible free models')
            return 1
        for index, model in enumerate(candidates, 1):
            print(f'DIAG | OPENROUTER/model{index} | selected={model}')
            status, response = request('/chat/completions', payload={
                'model': model,
                'messages': [{'role': 'user', 'content': 'Reply with exactly: OK'}],
                'max_tokens': 24,
                'temperature': 0,
                'provider': {'allow_fallbacks': False},
            })
            if status != 200:
                print(f'DIAG | OPENROUTER/chat{index} | FAIL | HTTP={status} | {safe_error(response)}')
                # Account-wide limit: further attempts are unlikely to help and waste quota.
                if status in (401, 402, 403) or (status == 429 and 'credit_or_key_limit' in safe_error(response)):
                    break
                continue
            choices = response.get('choices', []) if isinstance(response, dict) else []
            content = choices[0].get('message', {}).get('content') if choices and isinstance(choices[0], dict) else None
            if isinstance(content, str) and content.strip():
                print(f'DIAG | OPENROUTER/chat{index} | OK | HTTP=200 | nonempty response')
                print('DIAG | COMPLETE | API connectivity only; prediction accuracy not measured')
                return 0
            print(f'DIAG | OPENROUTER/chat{index} | FAIL | HTTP=200 but no text response')
        print('DIAG | COMPLETE | no successful free-model response')
        return 1
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        print(f'DIAG | OPENROUTER | FAIL | {type(exc).__name__}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
