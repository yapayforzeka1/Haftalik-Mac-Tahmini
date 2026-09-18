"""Manual, bounded provider checks. No Telegram, archives or automatic retries."""
from __future__ import annotations
import json
import os
import re
import httpx
import ai_pool


def redact(value):
    text = str(value)
    # Remove all configured secrets, even when echoed in a provider error.
    for key, secret in os.environ.items():
        if secret and any(part in key.upper() for part in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'https?://[^\s<>"\']+', '[URL]', text)
    text = re.sub(r'(?i)bearer\s+[^\s,"}]+', 'Bearer [REDACTED]', text)
    text = re.sub(r'(?i)((?:api[_-]?key|token|authorization|secret)[\"\']?\s*[:=]\s*[\"\']?)[^\s,"\'}]+', r'\1[REDACTED]', text)
    return ' '.join(text.split())[:1500]


def error_description(response):
    # Do not dump headers, requests, successful content or entire error objects.
    try:
        body = response.json()
    except ValueError:
        return 'NON_JSON_ERROR_BODY'
    messages = []
    def collect(value, depth=0):
        if depth > 5:
            return
        if isinstance(value, dict):
            for key in ('message', 'msg', 'code', 'type', 'status', 'param', 'loc'):
                item = value.get(key)
                if isinstance(item, (str, int)):
                    messages.append(f'{key}={item}')
                elif key == 'loc' and isinstance(item, list):
                    messages.append('loc=' + '/'.join(str(x) for x in item))
            for key in ('error', 'errors', 'detail', 'details'):
                if key in value:
                    collect(value[key], depth + 1)
        elif isinstance(value, list):
            for item in value[:5]:
                collect(item, depth + 1)
        elif isinstance(value, str):
            messages.append(value)
    collect(body)
    return redact(' | '.join(messages)) if messages else 'ERROR_MESSAGE_NOT_PROVIDED'


def probe(client, name, url, headers, body):
    try:
        response = client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        print(f'DIAG | {name} | NETWORK_ERROR | {type(exc).__name__}', flush=True)
        return False
    if response.is_success:
        print(f'DIAG | {name} | OK | HTTP={response.status_code}', flush=True)
        return True
    # Prefix each single-line message so it cannot be a workflow command.
    print(f'DIAG | {name} | FAIL | HTTP={response.status_code} | {error_description(response)}', flush=True)
    retry = response.headers.get('retry-after', '')
    if re.fullmatch(r'\d{1,7}(?:\.\d{1,3})?', retry):
        print(f'DIAG | {name} | Retry-After={retry}', flush=True)
    return False


def run(client):
    simple = 'Return only this JSON object: {"ok":true}'
    for provider in ('GEMINI', 'MISTRAL', 'COHERE'):
        key = os.getenv(provider + '_API_KEY')
        if not key:
            print(f'DIAG | {provider} | MISSING_API_KEY', flush=True)
            continue
        model = getattr(ai_pool, provider + '_MODEL')
        print(f'DIAG | {provider} | model={redact(model)}', flush=True)
        if provider == 'GEMINI':
            # Model identifiers must stay within the fixed API endpoint.
            if not re.fullmatch(r'[a-zA-Z0-9_.-]+', model):
                print('DIAG | GEMINI | INVALID_MODEL_IDENTIFIER', flush=True)
                continue
            probe(client, 'GEMINI/basic',
                  f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                  {'x-goog-api-key':key},
                  {'contents':[{'parts':[{'text':simple}]}],
                   'generationConfig':{'maxOutputTokens':128}})
        elif provider == 'MISTRAL':
            probe(client, 'MISTRAL/basic', 'https://api.mistral.ai/v1/chat/completions',
                  {'Authorization':'Bearer ' + key},
                  {'model':model,'messages':[{'role':'user','content':simple}], 'max_tokens':128})
        else:
            url = 'https://api.cohere.com/v2/chat'
            headers = {'Authorization':'Bearer ' + key}
            body = {'model':model,'messages':[{'role':'user','content':simple}], 'max_tokens':128}
            if not probe(client, 'COHERE/basic', url, headers, body):
                print('DIAG | COHERE/prediction | SKIPPED_BASIC_FAILED', flush=True)
                continue
            prompt = ai_pool.build_prompt('Test Home', 'Test Away',
                                         {'diagnostic':True, 'note':'Synthetic data; no real match statistics.'}, {}, {})
            body.update(messages=[{'role':'system','content':'Return only the requested JSON object. Keep reasons concise.'},
                                  {'role':'user','content':prompt}],
                        response_format={'type':'json_object'}, temperature=0.1, max_tokens=2048)
            if model.startswith(('command-a-plus', 'command-a-reasoning')):
                body['thinking'] = {'type':'disabled'}
            probe(client, 'COHERE/prediction', url, headers, body)
    print('DIAG | COMPLETE | OK means HTTP acceptance, not prediction quality.', flush=True)


if __name__ == '__main__':
    # The synchronous transport has retries disabled by default.
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        run(client)
