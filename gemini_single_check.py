"""One Gemini SDK request, no retry, football API, Telegram or other models."""
import os
from pathlib import Path
import time

import ai_pool
from gemini_budget import BudgetDeferred, GeminiRequestBudget
from storage import StateError


def run(*, budget=None, request=None):
    if not os.getenv('GEMINI_API_KEY'):
        print('GEMINI CHECK | FAIL | stage=CONFIG | reason=MISSING_API_KEY')
        return 2
    if budget is None:
        budget = GeminiRequestBudget(
            Path(__file__).resolve().parent / 'data/gemini_usage.json',
            ai_pool.GEMINI_MODEL, rpm=5, rpd=20,
        )
    request = request or ai_pool._gemini
    stage = 'BUDGET'
    try:
        budget.reserve(deadline=time.monotonic() + 95)
        print('GEMINI CHECK | request=1 | retries=0', flush=True)
        stage = 'REQUEST'
        started = time.monotonic()
        # Use the production SDK wrapper unchanged; it disables SDK retries.
        raw = request('Return only this JSON object: {"ok":true}')
        elapsed = time.monotonic() - started
        stage = 'PARSE'
        result = ai_pool._extract_json(raw)
        if result.get('ok') is not True:
            print('GEMINI CHECK | FAIL | stage=VALIDATE | reason=UNEXPECTED_JSON')
            return 1
        print(f'GEMINI CHECK | OK | JSON_OK | seconds={elapsed:.1f}', flush=True)
        return 0
    except BudgetDeferred as error:
        print(f'GEMINI CHECK | SKIPPED | stage=BUDGET | reason={error.category} | retry_after={error.retry_after}')
        return 2
    except StateError:
        print('GEMINI CHECK | FAIL | stage=BUDGET | reason=LEDGER_INVALID')
        return 2
    except Exception as error:
        # Never expose provider body, request, key, prompt or raw model response.
        category = ai_pool.safe_error(error)
        allowed = {'QUOTA_OR_RATE_LIMIT', 'TIMEOUT', 'AUTH_ERROR', 'MODEL_UNAVAILABLE',
                   'MODEL_OR_ENDPOINT_NOT_FOUND', 'PROVIDER_UNAVAILABLE', 'INVALID_REQUEST',
                   'SDK_IMPORT_ERROR', 'SDK_ARGUMENT_ERROR', 'SDK_RESPONSE_ERROR',
                   'CONNECTION_ERROR', 'INVALID_JSON', 'EMPTY_RESPONSE',
                   'RESPONSE_TRUNCATED', 'RESPONSE_STOPPED'}
        category = category if category in allowed else 'SDK_ERROR'
        status = ai_pool.error_http_status(error)
        detail = ai_pool.safe_error_detail(error)
        print(f'GEMINI CHECK | FAIL | stage={stage} | reason={category} | HTTP={status or "-"} | detail={detail}')
        return 1


if __name__ == '__main__':
    raise SystemExit(run())
