"""Offline, zero-token checks of independent, frozen experimental scores."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from experimental_scores import (
    calculate_experimental_scores, freeze_prospective_experiments,
    METHOD_AVERAGE, METHOD_MODE,
)

START = '2030-10-20T17:00:00+00:00'
CREATED = '2030-10-20T16:40:00+00:00'


def vote(name, score, *, success=True, outcome=None, model_id=None):
    if score is None:
        return {'model': name, 'success': False, 'result': None, 'error': '503'}
    h, a = map(int, score.split('-'))
    return {'model': name, 'success': success, 'result': {
        'score': score, 'outcome': outcome or ('HOME' if h > a else 'AWAY' if a > h else 'DRAW'),
        'model_id': model_id or 'stable/' + name, 'confidence': 50}}


def projection(scores):
    records = [vote(f'Model-{i}', score) for i, score in enumerate(scores)]
    return calculate_experimental_scores(records, match_id='875300', created_at=CREATED)


def methods(out):
    return out['methods'][METHOD_AVERAGE], out['methods'][METHOD_MODE]


def test_five_models_average_and_unique_mode():
    a, m = methods(projection(['2-1', '2-1', '1-0', '3-2', '0-1']))
    assert a['predicted_score'] == '2-1'  # sums 8 and 5 / five
    assert a['predicted_outcome'] == 'HOME'
    assert m['predicted_score'] == '2-1'
    assert len(a['models_used']) == 5 and a['valid_ai_count'] == 5
    assert a['classification'] == 'PROSPECTIVE'
    assert a['version'] == 1 and a['source_votes_sha256']


def test_three_valid_models_with_two_failed():
    a, m = methods(projection(['1-0', '2-1', '0-0', None, None]))
    assert a['predicted_score'] == '1-0' and a['valid_ai_count'] == 3
    assert m['predicted_score'] is None and m['failure_reason'] == 'NO_REPEATED_SCORE'


def test_two_valid_models_no_average_but_mode_may_exist():
    a, m = methods(projection(['2-1', '2-1', None, None, None]))
    assert a['predicted_score'] is None and a['failure_reason'] == 'MIN_3_VALID_AI'
    assert m['predicted_score'] == '2-1'


def test_zero_or_one_valid_model():
    for scores in ([None] * 5, ['1-1', None, None, None, None]):
        a, m = methods(projection(scores))
        assert a['predicted_score'] is None and m['predicted_score'] is None


def test_tied_top_score_does_not_implicitly_break_tie():
    a, m = methods(projection(['2-1', '2-1', '1-0', '1-0', '0-0']))
    assert a['predicted_score'] == '1-0'  # home 6/5; away 2/5
    assert m['predicted_score'] is None and m['failure_reason'] == 'TIED_TOP_SCORES'


def test_five_unique_scores_no_mode():
    a, m = methods(projection(['0-0','1-0','0-1','2-0','0-2']))
    assert m['predicted_score'] is None and m['failure_reason'] == 'NO_REPEATED_SCORE'


def test_half_up_rounding_is_not_bankers_rounding():
    a, _ = methods(projection(['1-2', '2-3', '0-2', '3-3']))
    assert a['predicted_score'] == '2-3'  # home 1.5, away 2.5
    assert a['predicted_outcome'] == 'AWAY'


def test_score_average_can_disagree_with_consensus_without_mutating_it():
    votes = [vote('A','0-2'), vote('B','0-2'), vote('C','1-2'),
             vote('D','4-0'), vote('E','4-0')]
    original = copy.deepcopy(votes)
    out = calculate_experimental_scores(votes, match_id='m', created_at=CREATED)
    assert out['methods'][METHOD_AVERAGE]['predicted_score'] == '2-1'
    assert votes == original


def test_ineligible_votes_are_excluded_and_unique_per_model():
    votes = [vote('A','1-0'), vote('B','2-1'), vote('C','3-2'),
             vote('D','0-2', success=False), vote('E','2-1', outcome='AWAY'),
             {'model':'F', 'success':True, 'result':{'score':'junk', 'outcome':'DRAW'}},
             vote('A','8-8')]
    out = calculate_experimental_scores(votes, match_id='m', created_at=CREATED)
    a, m = methods(out)
    assert a['valid_ai_count'] == 3
    assert a['predicted_score'] == '2-1'
    assert m['failure_reason'] == 'NO_REPEATED_SCORE'
    assert [x['model_id'] for x in a['models_used']] == ['stable/A','stable/B','stable/C']


def test_freeze_is_one_way_and_strictly_prematch():
    row = {'match_id': 900, 'match_utc': START,
           'ai_votes': [vote('A','2-1'), vote('B','2-1'), vote('C','1-0')]}
    old = copy.deepcopy(row['ai_votes'])
    assert freeze_prospective_experiments(row, created_at=CREATED)
    first = copy.deepcopy(row['experimental_predictions'])
    row['ai_votes'].append(vote('D','4-0'))
    assert not freeze_prospective_experiments(row, created_at=CREATED)
    assert row['experimental_predictions'] == first
    assert row['ai_votes'][:3] == old
    after = {'match_id':900, 'match_utc':START, 'ai_votes': old}
    assert not freeze_prospective_experiments(after, created_at=START)
    assert not freeze_prospective_experiments(after, created_at='2030-10-20T17:01:00+00:00')
    assert 'experimental_predictions' not in after


def test_backtest_never_masquerades_as_prospective():
    result = calculate_experimental_scores([vote('A','1-1')], match_id='1',
                                            created_at=CREATED, classification='BACKTEST')
    assert result['classification'] == 'BACKTEST'
    assert all(v['classification']=='BACKTEST' for v in result['methods'].values())
    with pytest.raises(ValueError):
        calculate_experimental_scores([], match_id='1', created_at=CREATED, classification='LIVE')


def test_real_archive_is_readonly_and_not_backfilled():
    path = Path('match_predictions.json')
    original_bytes = path.read_bytes()
    data = json.loads(original_bytes)
    snapshot = copy.deepcopy(data)
    for row in data.values():
        if row.get('actual') or row.get('final_sent'):
            assert not freeze_prospective_experiments(row, created_at=START)
    assert data == snapshot
    assert path.read_bytes() == original_bytes


def test_no_new_network_or_ai_dependencies():
    import experimental_scores as exp
    # Pure calculation module intentionally imports only stdlib modules.
    assert not any(k in exp.__dict__ for k in ('requests','genai','Groq','cohere'))


def test_live_runner_saves_exactly_one_prematch_snapshot(monkeypatch):
    import runner
    from ai_pool import AIVote
    from learning import new_state

    tick = datetime(2030, 10, 20, 16, 40, tzinfo=timezone.utc)
    monkeypatch.setattr(runner, 'now', lambda: tick)
    monkeypatch.setattr(runner, 'utcnow', lambda: tick.isoformat())
    monkeypatch.setattr(runner, 'official_xi', lambda *_: {
        'status':'ANNOUNCED', 'home':[{'name':f'H{i}'} for i in range(11)],
        'away':[{'name':f'A{i}'} for i in range(11)]})
    monkeypatch.setattr(runner, 'prepare_context', lambda *_: {'home':{}, 'away':{}})
    calls=[]

    def pool(*args,**kwargs):
        calls.append('prediction')
        return [AIVote(v['model'],v['success'],v.get('result'),v.get('error'))
                for v in [vote('Gemini','2-1'),vote('Qwen','2-1'),vote('Cohere','1-0'),
                          vote('GPT-OSS','0-1'),vote('Clef',None)]]

    monkeypatch.setattr(runner, 'run_ai_pool', pool)
    fixture = {'id': 876530, 'utcDate':START, 'status':'TIMED',
               'homeTeam':{'id':1,'name':'Club A'}, 'awayTeam':{'id':2,'name':'Club B'}}
    record = runner.new_record(fixture, new_state())
    assert runner.prepare_prediction(record, fixture, None, {}, new_state(), lambda:None,
                                     float('inf'))
    assert record['prediction_ready']
    assert record['experimental_predictions']['classification'] == 'PROSPECTIVE'
    assert record['experimental_predictions']['methods'][METHOD_AVERAGE]['valid_ai_count'] == 4
    archived = copy.deepcopy(record)
    assert runner.prepare_prediction(record, fixture, None, {}, new_state(), lambda:None,
                                     float('inf'))
    assert record == archived and calls == ['prediction']
    assert record['published_consensus'] == archived['published_consensus']
    assert 'experimental_predictions' not in record.get('prediction_text', '')


def test_visual_displays_successful_count_separately_from_common_vote(monkeypatch):
    import match_report
    from PIL import Image, ImageDraw

    record = {'ai_votes': [vote('A','2-1'), vote('B','2-1'),
                           vote('C','1-2'), vote('D','1-2'), vote('E',None)],
              'home_team':'A', 'away_team':'B', 'total_ai':5}
    output=[]
    original = match_report._draw_center

    def capture(draw,xy,value,*args):
        output.append(str(value))
        return original(draw,xy,value,*args)

    monkeypatch.setattr(match_report,'_draw_center',capture)
    im=Image.new('RGB',(1480,200))
    match_report._draw_consensus_cell(ImageDraw.Draw(im),0,record)
    assert 'Başarılı Tahmin' in output
    assert 'Üreten AL: 4/5' in output
    assert 'Ortak karar yok' in output
    assert not any('OY' in line for line in output)


def test_read_only_historical_votes_generate_backtest_only():
    # Retrospective experiments are never inserted into historical archive rows.
    source = Path('match_predictions.json')
    before = source.read_bytes()
    history = json.loads(before)
    generated = []
    for match_id, row in history.items():
        if not row.get('ai_votes'):
            continue
        generated.append(calculate_experimental_scores(
            row['ai_votes'], match_id=match_id, created_at='2030-12-01T00:00:00+00:00',
            classification='BACKTEST'))
    assert generated
    assert all(g['classification'] == 'BACKTEST' for g in generated)
    assert all(e['classification'] == 'BACKTEST' for g in generated for e in g['methods'].values())
    assert source.read_bytes() == before
