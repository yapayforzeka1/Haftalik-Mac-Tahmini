"""Two manual Cohere comparisons; no retries or production side effects."""
import os
import httpx
import ai_pool
from diagnose_providers import error_description, redact


def validate_response(body):
    if not isinstance(body, dict):
        return 'INVALID_RESPONSE'
    finish = str(body.get('finish_reason', '')).upper()
    if finish != 'COMPLETE':
        return 'RESPONSE_TRUNCATED' if finish == 'MAX_TOKENS' else 'RESPONSE_NOT_COMPLETE'
    message = body.get('message')
    if not isinstance(message, dict) or not isinstance(message.get('content'), list):
        return 'INVALID_RESPONSE'
    text = '\n'.join(b.get('text', '') for b in message['content']
                     if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str))
    try:
        prediction = ai_pool._extract_json(text)
    except (ValueError, TypeError):
        return 'INVALID_JSON'
    try:
        ai_pool._normalize(prediction, 'Test Home', 'Test Away')
        if not isinstance(prediction.get('short_reason'), str) or not prediction['short_reason'].strip():
            return 'MISSING_SHORT_REASON'
        if not isinstance(prediction.get('reasons'), list) or not prediction['reasons']:
            return 'MISSING_REASONS'
    except (ValueError, TypeError, AttributeError, OverflowError):
        return 'INVALID_PREDICTION'
    return 'VALID_PREDICTION'


def run(client):
    key = os.getenv('COHERE_API_KEY')
    if not key:
        print('COMPARE | COHERE | MISSING_API_KEY', flush=True)
        return
    print(f'COMPARE | COHERE | model={redact(ai_pool.COHERE_MODEL)}', flush=True)
    # Exactly the same synthetic prompt as the previous diagnostic.
    prompt = ai_pool.build_prompt('Test Home', 'Test Away',
                                 {'diagnostic':True, 'note':'Synthetic data; no real match statistics.'}, {}, {})
    base = {'model':ai_pool.COHERE_MODEL,
            'messages':[{'role':'system','content':'Return only the requested JSON object. Keep reasons concise.'},
                        {'role':'user','content':prompt}],
            'temperature':0.1, 'max_tokens':2048}
    variants = [
        ('JSON_NO_THINKING_PARAMETER', {'response_format':{'type':'json_object'}}),
        ('TEXT_THINKING_DISABLED', {'thinking':{'type':'disabled'}}),
    ]
    for name, options in variants:
        try:
            response = client.post('https://api.cohere.com/v2/chat',
                                   headers={'Authorization':'Bearer '+key}, json={**base, **options})
        except httpx.HTTPError as error:
            print(f'COMPARE | {name} | NETWORK_ERROR | {type(error).__name__}', flush=True)
            continue
        if not response.is_success:
            print(f'COMPARE | {name} | HTTP={response.status_code} | {error_description(response)}', flush=True)
            if response.status_code in {401,403,429}:
                print('COMPARE | STOP | AUTH_OR_RATE_LIMIT', flush=True)
                break
            continue
        try:
            result = validate_response(response.json())
        except ValueError:
            result = 'INVALID_RESPONSE'
        print(f'COMPARE | {name} | HTTP={response.status_code} | {result}', flush=True)
    print('COMPARE | COMPLETE | Synthetic checks only; production settings unchanged.', flush=True)


if __name__ == '__main__':
    with httpx.Client(timeout=45, follow_redirects=False) as client:
        run(client)
