from ai_pool import AIVote
from consensus_engine import build_consensus
from messages import prediction_tables

def test_two_two_one_has_no_common():
    votes = [AIVote(str(i), True, {'outcome': o, 'score': s, 'confidence': 50}) for i,(o,s) in enumerate([('HOME','2-1'),('HOME','1-0'),('DRAW','1-1'),('DRAW','0-0'),('AWAY','0-1')])]
    result = build_consensus(votes, min_successful=3)
    assert result['outcome'] is None
    assert result['score'] is None

def test_three_votes_win():
    votes = [AIVote(str(i), True, {'outcome': o, 'score': s, 'confidence': 50}) for i,(o,s) in enumerate([('HOME','2-1'),('HOME','2-1'),('HOME','1-0'),('DRAW','1-1'),('AWAY','0-1')])]
    result = build_consensus(votes, min_successful=3)
    assert result['outcome'] == 'HOME'
