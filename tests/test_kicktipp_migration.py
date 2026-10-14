"""Zero-network scoring migration regression tests."""
import copy

from history_engine import grade_record
from runner import regrade_archived_results
from scoring import VERSION, outcome_points, score_prediction


def _prediction(matchday, score, actual, success=True):
    h, a = map(int, score.split('-'))
    return {
        'matchday': matchday, 'prediction_ready': True, 'final_sent': True,
        'result_sent': True, 'result_receipt': {'complete': True},
        'prediction_kind': 'AI', 'grading_version': '3:6-5-3-2-0:REGULAR',
        'actual': {'home': actual[0], 'away': actual[1], 'scope': 'REGULAR_90', 'status': 'FINISHED'},
        'ai_votes': [
            {'model': 'A', 'success': success, 'result': {'score': score, 'outcome': 'HOME' if h>a else 'DRAW' if h==a else 'AWAY'}, 'points': 6},
            {'model': 'B', 'success': False, 'result': None, 'points': None},
        ],
        'published_consensus': {'outcome': 'HOME', 'score': score},
    }


def test_migrate_first_and_second_week_without_changing_original_prediction_or_receipts():
    rows = {'1': _prediction(1, '2-1', (2, 1)), '2': _prediction(2, '1-1', (2, 2))}
    before = copy.deepcopy(rows)
    assert regrade_archived_results(rows) == 2
    assert rows['1']['ai_votes'][0]['points'] == 8
    assert rows['2']['ai_votes'][0]['points'] == 6
    for key in rows:
        assert rows[key]['grading_version'] == VERSION
        assert rows[key]['pre_kicktipp_evaluation']['grading_version'] == before[key]['grading_version']
        assert [v['points'] for v in rows[key]['pre_kicktipp_evaluation']['votes']] == [v['points'] for v in before[key]['ai_votes']]
        assert rows[key]['result_receipt'] == before[key]['result_receipt']
        assert rows[key]['result_sent'] == before[key]['result_sent']
        assert rows[key]['published_consensus'] == before[key]['published_consensus']
    snapshot = copy.deepcopy(rows)
    assert regrade_archived_results(rows) == 0
    assert rows == snapshot


def test_unverified_results_untouched_and_missing_ai_unscored():
    rows = {'no_result': {'prediction_ready':True, 'ai_votes': []},
            'wrong_scope': _prediction(2, '2-1', (2, 1)),
            'ready': _prediction(1, '3-0', (2, 1))}
    rows['wrong_scope']['actual']['scope'] = 'EXTRA_TIME'
    assert regrade_archived_results(rows) == 1
    assert rows['ready']['ai_votes'][0]['points'] == 4
    assert rows['ready']['ai_votes'][1]['points'] is None
    assert 'legacy_evaluation' not in rows['wrong_scope']
    assert 'legacy_evaluation' not in rows['no_result']


def test_no_score_ensemble_and_draws():
    assert outcome_points('DRAW','DRAW') == 4
    assert outcome_points('HOME','HOME') == 4
    assert score_prediction('0-0', 1, 1) == 6
    assert score_prediction('3-2', 2, 1) == 6
    assert score_prediction('3-0', 2, 1) == 4
    record = _prediction(1, '2-1', (2, 1))
    record['ai_votes'][0]['result']['score'] = None
    grade_record(record)
    assert record['ai_votes'][0]['points'] is None


def test_already_existing_legacy_grade_is_never_overwritten():
    record = _prediction(1, '2-1', (2,1))
    record['legacy_evaluation'] = {'grading_version': 2, 'consensus_points': 3}
    before = copy.deepcopy(record['legacy_evaluation'])
    assert regrade_archived_results({'1':record}) == 1
    assert record['legacy_evaluation'] == before
    assert record['pre_kicktipp_evaluation']['grading_version'] == '3:6-5-3-2-0:REGULAR'
    assert record['pre_kicktipp_evaluation']['votes'][0]['points'] == 6
    assert record['ai_votes'][0]['points'] == 8
