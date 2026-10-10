#!/usr/bin/env python3
"""Isolated, capped historical Clef-omni evaluation; never changes project data."""
import argparse
import datetime as dt
import json
import os
import pathlib
import time
import urllib.error
import urllib.request

SCORES = {f'{h}_{a}': f'{h}-{a}' for h in range(5) for a in range(5)}

def parse_date(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None

def summarize_side(side, kickoff):
    recent = (side.get('last_5') or {}).get('matches') or []
    safe = []
    for m in recent:
        when = parse_date(m.get('date'))
        if when is None or when >= kickoff:
            continue
        safe.append({'date': m.get('date'), 'competition': m.get('competition'),
                     'opponent': m.get('opponent'), 'venue': m.get('venue'),
                     'goals_for': m.get('goals_for'), 'goals_against': m.get('goals_against')})
    safe.sort(key=lambda x: x['date'], reverse=True)
    return {'recent_completed_matches_before_kickoff': safe[:5]}

def make_state(record):
    kickoff = parse_date(record.get('match_utc'))
    if kickoff is None:
        raise ValueError('Missing kickoff time')
    ctx = record.get('context') or {}
    return json.dumps({
        'disclaimer': 'Historical match evaluation. Predict as if before kickoff. No final result supplied.',
        'home_team': record['home_team'], 'away_team': record['away_team'],
        'kickoff_utc': record['match_utc'],
        'home': summarize_side(ctx.get('home') or {}, kickoff),
        'away': summarize_side(ctx.get('away') or {}, kickoff)
    }, ensure_ascii=False)

def call_api(state, token, account):
    url = f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/cloudflare/clef-omni'
    payload = {'model': 'clef-omni', 'state': state, 'questions': {
        'result': {'type': 'choice', 'instructions': 'Predict full-time 90-minute match outcome.',
                   'criteria': {'1': 'Home win', 'X': 'Draw', '2': 'Away win'}},
        'score': {'type': 'choice', 'instructions': 'Predict full-time exact score from the listed options only.',
                  'criteria': SCORES}}}
    request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=45) as response:
        body = json.load(response)
    if body.get('success') is not True:
        raise ValueError('Cloudflare returned success=false')
    answers = (body.get('result') or {}).get('answers') or {}
    outcome = (answers.get('result') or {}).get('choice')
    score = (answers.get('score') or {}).get('choice')
    if outcome not in ('1', 'X', '2') or score not in SCORES:
        raise ValueError('Unexpected response choices')
    return outcome, SCORES[score], (body.get('result') or {}).get('usage', {})

def actual_outcome(h, a):
    return '1' if h > a else '2' if a > h else 'X'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=16)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.limit <= 16:
        parser.error('limit must be between 1 and 16')
    records = json.loads(pathlib.Path('match_predictions.json').read_text(encoding='utf-8'))
    if not isinstance(records, dict):
        raise SystemExit('Unexpected match_predictions.json format')
    selected = []
    for match_id, record in sorted(records.items(), key=lambda item: (item[1].get('match_utc', ''), item[0])):
        actual = record.get('actual') or {}
        if actual.get('status') != 'FINISHED' or not isinstance(actual.get('home'), int) or not isinstance(actual.get('away'), int):
            continue
        selected.append((match_id, record))
    selected = selected[:args.limit]
    if not selected:
        raise SystemExit('No completed matches found')
    token = os.environ.get('CF_TOKEN')
    account = os.environ.get('CF_ACCOUNT')
    if not args.dry_run and (not token or not account):
        raise SystemExit('Missing Cloudflare credentials')
    rows = []
    for match_id, record in selected:
        state = make_state(record)
        row = {'match_id': match_id, 'home_team': record['home_team'], 'away_team': record['away_team'],
               'actual_score': f"{record['actual']['home']}-{record['actual']['away']}",
               'actual_outcome': actual_outcome(record['actual']['home'], record['actual']['away']),
               'prediction_created_at': record.get('prediction_created_at'),
               'historical_context_warning': 'Archived context not independently verified as originally available before kickoff'}
        if args.dry_run:
            row['state'] = json.loads(state)
        else:
            try:
                outcome, score, usage = call_api(state, token, account)
                row.update({'predicted_outcome': outcome, 'predicted_score': score,
                            'outcome_correct': outcome == row['actual_outcome'],
                            'score_correct': score == row['actual_score'], 'usage': usage})
            except (urllib.error.URLError, ValueError, TimeoutError) as exc:
                row['error'] = f'{type(exc).__name__}: {getattr(exc, "code", str(exc))}'
                rows.append(row)
                print(f'API request failed for match {match_id}; stopping to avoid repeated quota consumption.')
                break
        rows.append(row)
        print(f"{len(rows)}/{len(selected)}: {record['home_team']} - {record['away_team']} " +
              ('DRY RUN' if args.dry_run else f"{row.get('predicted_outcome')} {row.get('predicted_score')}"), flush=True)
        if not args.dry_run:
            time.sleep(0.3)
    valid = [r for r in rows if 'predicted_outcome' in r]
    summary = {'requested': args.limit, 'selected': len(selected), 'attempted': len(rows),
               'valid': len(valid), 'outcome_correct': sum(r.get('outcome_correct', False) for r in valid),
               'score_correct': sum(r.get('score_correct', False) for r in valid),
               'note': 'Retrospective evaluation; not a prospective accuracy estimate. Scores restricted to 0-0 through 4-4.'}
    pathlib.Path('cloudflare_backtest_results.json').write_text(
        json.dumps({'summary': summary, 'matches': rows}, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not args.dry_run and len(valid) != len(selected):
        raise SystemExit('Incomplete backtest; see uploaded artifact')

if __name__ == '__main__':
    main()
