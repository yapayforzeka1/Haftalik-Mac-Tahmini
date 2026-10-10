"""Regression checks for the fixed three-identical-outcome rule."""
from dataclasses import asdict
from ai_pool import AIVote
from consensus_engine import build_consensus
from messages import prediction_tables
from match_report import _consensus


def sample(outcomes):
    scores = {'HOME': '2-1', 'AWAY': '1-2', 'DRAW': '1-1'}
    votes = [AIVote(str(i), True, {'outcome': o, 'score': scores[o], 'confidence': 50}) for i, o in enumerate(outcomes)]
    record = {'home_team': 'Home', 'away_team': 'Away', 'match_time': '19:30',
              'ai_votes': [asdict(v) for v in votes], 'prediction_kind': 'AI'}
    return votes, record


def test_two_of_three_has_no_common_result_or_score():
    votes, record = sample(['HOME','HOME','AWAY'])
    c = build_consensus(votes)
    assert c['outcome'] is None and c['score'] is None
    assert prediction_tables(record)['mode'] == 'NO_COMMON'
    assert _consensus(record)[0] == 'Ortak karar yok'
    assert _consensus(record)[1] == '—'
    assert len(prediction_tables(record)['rows']) == 3


def test_three_of_three_has_common_result_and_score():
    votes, record = sample(['HOME'] * 3)
    assert build_consensus(votes)['outcome'] == 'HOME'
    assert prediction_tables(record)['mode'] == 'NORMAL'
    assert _consensus(record)[0] == 'Home'


def test_two_two_one_no_common_and_five_individuals():
    votes, record = sample(['HOME','HOME','DRAW','DRAW','AWAY'])
    assert build_consensus(votes)['outcome'] is None
    assert prediction_tables(record)['mode'] == 'NO_COMMON'
    assert len(prediction_tables(record)['rows']) == 5


def test_three_of_five_has_common_result():
    votes, record = sample(['HOME','HOME','HOME','DRAW','AWAY'])
    assert build_consensus(votes)['outcome'] == 'HOME'
    assert prediction_tables(record)['mode'] == 'NORMAL'
