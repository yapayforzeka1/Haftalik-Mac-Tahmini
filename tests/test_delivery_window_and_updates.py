from datetime import datetime, timedelta, timezone

import runner


def vote(name, score):
    return {'model': name, 'success': True, 'result': {'score': score}}


def test_partial_waits_until_15_minutes_and_complete_is_immediate():
    kickoff = datetime(2026, 12, 1, 20, 0, tzinfo=timezone.utc)
    record = {'match_utc': kickoff.isoformat(), 'prediction_complete': False,
              'ai_votes': [vote(str(i), '1-0') for i in range(4)]}
    assert not runner._prediction_photo_due(record, lambda: kickoff - timedelta(minutes=16))
    assert runner._prediction_photo_due(record, lambda: kickoff - timedelta(minutes=15))
    record['ai_votes'].append(vote('4', '1-0'))
    assert runner._prediction_photo_due(record, lambda: kickoff - timedelta(minutes=40))


def test_update_compares_delivered_snapshot_and_only_new_model(monkeypatch):
    kickoff = datetime(2026, 12, 1, 20, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(runner, 'now', lambda: kickoff - timedelta(minutes=5))
    sent = []
    def deliver(bot, chat, text, receipt, save, **kwargs):
        sent.append(text)
        receipt['complete'] = True
    monkeypatch.setattr(runner, 'deliver_text', deliver)
    old = {'winner_consensus': True, 'outcome': 'AWAY', 'score': '0-2'}
    new = {'winner_consensus': True, 'outcome': 'HOME', 'score': '1-2'}
    record = {'match_utc': kickoff.isoformat(), 'home_team': 'Lille', 'away_team': 'Bayern',
              'prediction_update_required': True, 'final_sent': True, 'prediction_complete': True,
              'delivered_consensus': old, 'consensus': new, 'delivered_models': ['a', 'b', 'c', 'd'],
              'ai_votes': [vote(x, '1-2') for x in ['a', 'b', 'c', 'd', 'GPT-OSS']]}
    runner.drain_prediction_updates({'1': record}, None, None, lambda: None)
    assert 'ORTAK KARAR DEĞİŞTİ' in sent[0]
    assert 'Önceki: Bayern II 🆕 Yeni: <b>Lille</b>' in sent[0]
    assert 'Önceki: 0-2 II 🆕 Yeni: <b>1-2</b>' in sent[0]
    assert 'GPT-OSS: 1-2' in sent[0]
    assert not record['prediction_update_required']
    assert record['delivered_consensus'] == new


def test_no_update_after_kickoff(monkeypatch):
    kickoff = datetime(2026, 12, 1, 20, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(runner, 'now', lambda: kickoff)
    monkeypatch.setattr(runner, 'deliver_text', lambda *args: (_ for _ in ()).throw(AssertionError('late message')))
    record = {'match_utc': kickoff.isoformat(), 'prediction_update_required': True, 'final_sent': True}
    runner.drain_prediction_updates({'1': record}, None, None, lambda: None)
