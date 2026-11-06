"""Telegram transport, receipts and retry boundaries without real messages."""
import copy
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS

import pytest
import requests
import runner
from telegram_io import Telegram, TelegramError, TelegramDeliveryUncertain

SECRET = 'private-token-and-url'
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def photo(tmp_path):
    path = tmp_path/'photo.png'
    path.write_bytes(b'offline-image')
    return path


def fake_response(status=200, data=None, invalid=False):
    def decode():
        if invalid: raise ValueError(SECRET)
        return data
    return NS(status_code=status, ok=200 <= status < 400, json=decode)


def test_photo_accepts_message_and_uses_separate_connect_read_timeouts(monkeypatch, photo, capsys):
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs)
        return fake_response(data={'ok': True, 'result': {'message_id': 42, 'chat': {'id': SECRET}}})
    monkeypatch.setattr(requests, 'post', post)
    result = Telegram(SECRET).photo(SECRET, photo)
    assert result['message_id'] == 42
    assert calls[0]['timeout'] == (10, 60) and len(calls) == 1
    output = capsys.readouterr().out
    assert 'status=SENT' in output and 'message_id=42' in output and SECRET not in output


@pytest.mark.parametrize('kind,reason', [
    (requests.ReadTimeout, 'READ_TIMEOUT'), (requests.ConnectTimeout, 'CONNECT_TIMEOUT'),
    (requests.Timeout, 'TIMEOUT'), (requests.ConnectionError, 'CONNECTION_ERROR'),
    (requests.RequestException, 'REQUEST_ERROR')])
def test_transport_failure_is_uncertain_with_safe_reason_and_no_internal_retry(monkeypatch, photo, kind, reason):
    calls = []
    def post(*args, **kwargs): calls.append(1); raise kind(SECRET)
    monkeypatch.setattr(requests, 'post', post)
    with pytest.raises(TelegramDeliveryUncertain) as caught:
        Telegram(SECRET).photo(SECRET, photo)
    assert caught.value.reason == reason and len(calls) == 1
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize('status,data,invalid,reason', [
    (503, {}, False, 'SERVER_ERROR'), (200, {}, True, 'INVALID_JSON'),
    (200, [], False, 'INVALID_RESPONSE'), (200, {}, False, 'MISSING_OK'),
    (200, {'ok': True}, False, 'MISSING_MESSAGE_ID'),
    (200, {'ok': True, 'result': {}}, False, 'MISSING_MESSAGE_ID'),
    (200, {'ok': True, 'result': {'message_id': True}}, False, 'MISSING_MESSAGE_ID'),
    (200, {'ok': True, 'result': {'message_id': 0}}, False, 'MISSING_MESSAGE_ID'),
])
def test_ambiguous_response_never_claims_success(monkeypatch, photo, status, data, invalid, reason):
    monkeypatch.setattr(requests, 'post', lambda *a, **k: fake_response(status, data, invalid))
    with pytest.raises(TelegramDeliveryUncertain) as caught:
        Telegram(SECRET).photo(SECRET, photo)
    assert caught.value.reason == reason and caught.value.http_status == status


def test_explicit_rejection_keeps_retry_after_without_body_or_url(monkeypatch, photo):
    monkeypatch.setattr(requests, 'post', lambda *a, **k: fake_response(429,
        {'ok': False, 'description': SECRET, 'parameters': {'retry_after': 900}}))
    with pytest.raises(TelegramError) as caught:
        Telegram(SECRET).photo(SECRET, photo)
    assert not isinstance(caught.value, TelegramDeliveryUncertain)
    assert caught.value.reason == 'API_REJECTED' and caught.value.http_status == 429
    assert caught.value.retry_after == 900 and SECRET not in str(caught.value)


@pytest.mark.parametrize('data,invalid', [({}, True), ([], False)])
def test_http_rejection_without_json_is_still_rejected(monkeypatch, photo, data, invalid):
    monkeypatch.setattr(requests, 'post', lambda *a, **k: fake_response(400, data, invalid))
    with pytest.raises(TelegramError) as caught:
        Telegram(SECRET).photo(SECRET, photo)
    assert not isinstance(caught.value, TelegramDeliveryUncertain)
    assert caught.value.reason == 'HTTP_ERROR'


def ready_record(mid='1'):
    return {'match_id': mid, 'home_team': 'Home', 'away_team': 'Away',
            'prediction_ready': True, 'message_format_version': 4,
            'match_utc': (NOW+timedelta(hours=1)).isoformat(),
            'ai_votes': [{'model': 'archived', 'success': True}], 'test_mode': True}


@pytest.fixture
def delivery(monkeypatch, photo):
    tick = [NOW]
    monkeypatch.setattr(runner, 'now', lambda: tick[0])
    monkeypatch.setattr('match_report.render_match_group_image', lambda *a, **k: photo)
    return tick


def test_group_stores_returned_id_on_all_records_and_does_not_resend(delivery):
    records = {'1': ready_record(), '2': ready_record('2')}
    calls, saves = [], []
    class Bot:
        def photo(self, *args): calls.append(1); return {'message_id': 77}
    before_votes = copy.deepcopy(records['1']['ai_votes'])
    def save(): saves.append(copy.deepcopy(records))
    runner.drain_delivery(records, Bot(), 'chat', save)
    runner.drain_delivery(records, Bot(), 'chat', save)
    assert calls == [1]
    assert any(s['1']['photo_delivery']['status'] == 'SENDING' for s in saves)
    for r in records.values():
        assert r['final_sent'] and r['photo_delivery']['message_id'] == 77
        assert r['prediction_receipt']['message_id'] == 77
        assert r['prediction_receipt']['group_size'] == 2
    assert records['1']['ai_votes'] == before_votes


def test_sent_receipt_recovery_keeps_message_id_without_sending(delivery):
    record = ready_record()
    record['photo_delivery'] = {'status': 'SENT', 'message_id': 91, 'group_size': 1}
    class Bot:
        def photo(self, *args): pytest.fail('Already sent')
    runner.drain_delivery({'1': record}, Bot(), 'chat', lambda: None)
    assert record['final_sent'] and record['prediction_receipt']['message_id'] == 91


def test_single_photo_stores_message_id(delivery):
    record = ready_record()
    bot = NS(photo=lambda *args: {'message_id': 31})
    runner.deliver_record(record, bot, 'chat', lambda: None)
    assert record['final_sent'] and record['prediction_receipt']['message_id'] == 31


def test_legacy_text_receipt_is_preserved(delivery):
    record = ready_record()
    receipt = {'complete': True, 'parts_sent': 1, 'message_ids': [12]}
    record.update(message_format_version=3, prediction_receipt=copy.deepcopy(receipt), image_required=True)
    bot = NS(photo=lambda *args: {'message_id': 31})
    runner.deliver_record(record, bot, 'chat', lambda: None)
    assert record['prediction_receipt'] == receipt
    assert record['photo_delivery']['message_id'] == 31


def test_uncertain_group_saves_reason_and_does_not_fall_back_or_retry_early(delivery, capsys):
    record = ready_record(); calls = []
    class Bot:
        def photo(self, *args):
            calls.append(1)
            raise TelegramDeliveryUncertain('redacted', reason='READ_TIMEOUT')
    for _ in range(2):
        runner.drain_delivery({'1': record}, Bot(), 'chat', lambda: None)
    state = record['photo_delivery']
    assert calls == [1] and state['status'] == 'UNCERTAIN'
    assert state['reason'] == 'READ_TIMEOUT' and not record.get('final_sent')
    assert 'reason=READ_TIMEOUT' in capsys.readouterr().out


def test_rejected_group_respects_server_retry_after_in_both_group_and_single_paths(delivery):
    record = ready_record(); calls = []
    class Bot:
        def photo(self, *args):
            calls.append(1)
            if len(calls) == 1:
                raise TelegramError('redacted', reason='API_REJECTED', http_status=429, retry_after=900)
            return {'message_id': 99}
    bot = Bot()
    runner.drain_delivery({'1': record}, bot, 'chat', lambda: None)
    assert calls == [1] and record['photo_delivery']['http_status'] == 429
    delivery[0] = NOW+timedelta(seconds=600)
    runner.drain_delivery({'1': record}, bot, 'chat', lambda: None)
    assert calls == [1]
    delivery[0] = NOW+timedelta(seconds=900)
    runner.drain_delivery({'1': record}, bot, 'chat', lambda: None)
    assert calls == [1, 1] and record['prediction_receipt']['message_id'] == 99


def test_checkpoint_failure_never_sends_photo(delivery):
    record = ready_record()
    bot = NS(photo=lambda *args: pytest.fail('Checkpoint failed'))
    def checkpoint(): raise OSError('offline')
    with pytest.raises(runner.StateError):
        runner.drain_delivery({'1': record}, bot, 'chat', lambda: None, checkpoint=checkpoint)
    assert 'photo_delivery' not in record


def test_visual_check_uses_same_transport_and_redacts_failure(monkeypatch, photo, capsys):
    import render_preview
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', SECRET)
    monkeypatch.setenv('TELEGRAM_CHAT_ID', SECRET)
    def fail(*args, **kwargs):
        raise TelegramDeliveryUncertain('redacted', reason='READ_TIMEOUT')
    monkeypatch.setattr(Telegram, 'photo', fail)
    with pytest.raises(SystemExit): render_preview.send_photo(photo, 'TEST')
    out = capsys.readouterr().out
    assert 'READ_TIMEOUT' in out and SECRET not in out


def test_visual_check_cannot_claim_success_without_credentials(monkeypatch, photo):
    import render_preview
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)
    with pytest.raises(SystemExit): render_preview.send_photo(photo, 'TEST')


def test_uncertain_group_stops_at_three_attempts_and_sends_one_review_notice(delivery):
    record = ready_record(); photos, notices = [], []
    class Bot:
        def photo(self, *args):
            photos.append(1)
            raise TelegramDeliveryUncertain('redacted', reason='READ_TIMEOUT')
        def call(self, *args, **kwargs): notices.append(1); return {'message_id': 123}
    for seconds in [0, 300, 900, 1800, 2400]:
        delivery[0] = NOW+timedelta(seconds=seconds)
        runner.drain_delivery({'1': record}, Bot(), 'chat', lambda: None)
    assert len(photos) == 3 and len(notices) == 1
    assert record['photo_delivery']['status'] == 'NEEDS_REVIEW'
    assert not record.get('final_sent')
