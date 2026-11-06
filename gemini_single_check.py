"""One Gemini SDK request, no retry, football API, Telegram or other models."""
import os
from pathlib import Path
import time
import re

import ai_pool
from gemini_budget import BudgetDeferred, GeminiRequestBudget
from storage import StateError, load_json


class CheckInputError(ValueError):
    pass


def archived_prompt(match_id, archive_path):
    """Read only the saved pre-match inputs; never append the actual result."""
    from runner import excluded_record
    if not re.fullmatch(r'[0-9]{1,12}', str(match_id)):
        raise CheckInputError()
    records = load_json(Path(archive_path), {})
    record = records.get(str(match_id))
    if (not isinstance(record, dict) or str(record.get('match_id')) != str(match_id)
            or excluded_record(record)
            or not all(isinstance(record.get(key), dict) for key in ('context', 'research'))
            or not all(isinstance(record.get(key), str) and record[key].strip()
                       for key in ('home_team', 'away_team'))
            or not isinstance(record.get('history', {}), dict)):
        raise CheckInputError()
    return ai_pool.build_prompt(record['home_team'], record['away_team'],
                                record['context'], record['research'], record.get('history', {})), record


def run(*, budget=None, request=None, mode='basic', match_id='', archive_path=None):
    if not os.getenv('GEMINI_API_KEY'):
        print('GEMINI CHECK | FAIL | stage=CONFIG | reason=MISSING_API_KEY')
        return 2
    if budget is None:
        budget = GeminiRequestBudget(
            Path(__file__).resolve().parent / 'data/gemini_usage.json',
            ai_pool.GEMINI_MODEL, rpm=5, rpd=20,
        )
    request = request or ai_pool._gemini
    print(f'GEMINI CHECK | model={ai_pool.GEMINI_MODEL}', flush=True)
    stage = 'INPUT'
    try:
        if mode == 'basic':
            prompt = 'Return only this JSON object: {"ok":true}'
            record = None
        elif mode == 'archived_prediction':
            archive_path = archive_path or Path(__file__).resolve().parent / 'match_predictions.json'
            prompt, record = archived_prompt(match_id, archive_path)
            print(f'GEMINI CHECK | mode=archived_prediction | match_id={match_id} | prompt_chars={len(prompt)}', flush=True)
        else:
            raise CheckInputError()
        stage = 'BUDGET'
        budget.reserve(deadline=time.monotonic() + 95)
        print('GEMINI CHECK | request=1 | retries=0', flush=True)
        stage = 'REQUEST'
        started = time.monotonic()
        # Use the production SDK wrapper unchanged; it disables SDK retries.
        raw = request(prompt)
        elapsed = time.monotonic() - started
        stage = 'PARSE'
        result = ai_pool._extract_json(raw)
        if mode == 'archived_prediction':
            stage = 'VALIDATE'
            result = ai_pool._normalize(result, record['home_team'], record['away_team'])
            print(f'GEMINI CHECK | OK | PREDICTION_JSON_OK | score={result["score"]} | outcome={result["outcome"]} | seconds={elapsed:.1f}', flush=True)
            return 0
        if result.get('ok') is not True:
            print('GEMINI CHECK | FAIL | stage=VALIDATE | reason=UNEXPECTED_JSON')
            return 1
        print(f'GEMINI CHECK | OK | JSON_OK | seconds={elapsed:.1f}', flush=True)
        return 0
    except CheckInputError:
        print('GEMINI CHECK | FAIL | stage=INPUT | reason=INVALID_ARCHIVED_INPUT')
        return 2
    except BudgetDeferred as error:
        print(f'GEMINI CHECK | SKIPPED | stage=BUDGET | reason={error.category} | retry_after={error.retry_after}')
        return 2
    except StateError:
        reason = 'ARCHIVE_INVALID' if stage == 'INPUT' else 'LEDGER_INVALID'
        print(f'GEMINI CHECK | FAIL | stage={stage} | reason={reason}')
        return 2
    except Exception as error:
        # Never expose provider body, request, key, prompt or raw model response.
        category = 'INVALID_PREDICTION' if stage == 'VALIDATE' else ai_pool.safe_error(error)
        allowed = {'QUOTA_OR_RATE_LIMIT', 'TIMEOUT', 'AUTH_ERROR', 'MODEL_UNAVAILABLE',
                   'MODEL_OR_ENDPOINT_NOT_FOUND', 'PROVIDER_UNAVAILABLE', 'INVALID_REQUEST',
                   'SDK_IMPORT_ERROR', 'SDK_ARGUMENT_ERROR', 'SDK_RESPONSE_ERROR',
                   'CONNECTION_ERROR', 'INVALID_JSON', 'EMPTY_RESPONSE',
                   'RESPONSE_TRUNCATED', 'RESPONSE_STOPPED', 'INVALID_PREDICTION'}
        category = category if category in allowed else 'SDK_ERROR'
        status = ai_pool.error_http_status(error)
        detail = ai_pool.safe_error_detail(error)
        print(f'GEMINI CHECK | FAIL | stage={stage} | reason={category} | HTTP={status or "-"} | detail={detail}')
        return 1


if __name__ == '__main__':
    raise SystemExit(run(mode=os.getenv('GEMINI_CHECK_MODE', 'basic'),
                         match_id=os.getenv('GEMINI_CHECK_MATCH_ID', '575394')))
