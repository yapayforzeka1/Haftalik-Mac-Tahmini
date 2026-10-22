import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_pool import AIVote, _normalize, build_prompt
from consensus_engine import build_consensus
from fallback import predict
from history_engine import grade_record
from learning import POLICIES, audit, digest, eligible, learning_context, maybe_propose, new_state, summarize
from messages import prediction_message
from operations import fingerprint, handle_callback, run_operations
from providers import predicted_xi, valid_xi
from runner import deliver_record, drain_delivery, new_record, prepare_prediction, refresh_results
from scoring import VERSION, regulation_score, score_prediction
from storage import StateError, load_json, save_json
from telegram_io import TelegramError, deliver_text

NOW = datetime(2026, 9, 17, 16, tzinfo=timezone.utc)


def vote(model, score, success=True):
    if not success:
        return {'model': model, 'success': False, 'result': None, 'error': 'QUOTA_OR_RATE_LIMIT'}
    h, a = map(int, score.split('-'))
    return {'model': model, 'success': True, 'result': {'score': score,
        'outcome': 'HOME' if h > a else 'AWAY' if h < a else 'DRAW', 'confidence': 55,
        'reasons': ['Form verisi'], 'factors_used': ['form']}, 'error': None}


def record():
    votes = [vote('a', '2-1'), vote('b', '2-1'), vote('c', '0-1'), vote('d', '1-0', False)]
    return {'match_id': '1', 'home_team': 'Ev', 'away_team': 'Deplasman',
            'match_time': '17.09.2026 19:30', 'match_utc': (NOW+timedelta(minutes=30)).isoformat(),
            'prediction_created_at': NOW.isoformat(), 'prediction_ready': True,
            'prediction_kind': 'AI', 'prediction_text': 'Önceden kaydedilmiş tahmin',
            'ai_votes': votes, 'consensus': build_consensus([AIVote(**v) for v in votes]),
            'context': {'official_xi': {'status': 'NOT_ANNOUNCED'}}, 'final_sent': False}


class FakeTelegram:
    def __init__(self, fail_at=0, updates=None):
        self.calls = []
        self.fail_at = fail_at
        self.updates = updates or []
    def call(self, method, **kwargs):
        self.calls.append((method, kwargs))
        if len(self.calls) == self.fail_at:
            raise TelegramError('simulated')
        if method == 'getUpdates':
            return self.updates
        return {'message_id': len(self.calls)}
    def photo(self, *args):
        self.calls.append(('photo', {}))
        if self.fail_at:
            raise TelegramError('photo failure')


@pytest.mark.parametrize('score,actual,points', [
    ('3-1',(3,1),8), ('2-0',(3,1),6), ('4-2',(3,1),6), ('2-1',(3,1),4),
    ('1-1',(3,1),0), ('1-1',(2,2),6), ('2-2',(2,2),8), ('0-2',(1,3),6),
    ('3-0',(0,3),0), ('bad',(0,0),0), (' 2 - 1 ',(2,1),8)])
def test_scoring(score, actual, points):
    assert score_prediction(score, *actual) == points


def test_regular_time_only():
    assert regulation_score({'score': {'duration': 'REGULAR', 'fullTime': {'home': 2, 'away': 1}}}) == (2,1)
    assert regulation_score({'score': {'duration': 'PENALTY_SHOOTOUT', 'fullTime': {'home': 7, 'away': 6}}}) is None
    assert regulation_score({'score': {'duration': 'EXTRA_TIME', 'regularTime': {'home': 1, 'away': 1},
                                      'fullTime': {'home': 2, 'away': 1}}}) == (1,1)
    assert regulation_score({'score': {'fullTime': {'home': 2, 'away': 1}}}) is None


def test_single_model_and_denominator():
    r = record()
    assert r['consensus']['outcome_share'] == 0
    assert r['consensus']['successful_ai'] == 3
    r['ai_votes'] = r['ai_votes'][:1]
    r['consensus'] = build_consensus([AIVote(**r['ai_votes'][0])])
    assert not r['consensus']['winner_consensus']
    assert 'bireysel tahmin' in prediction_message(r)
    r['actual'] = {'home':2, 'away':1}
    grade_record(r)
    assert r['ai_votes'][0]['points'] == 8
    assert r['consensus_points'] is None


def test_normal_message_uses_compact_votes_without_confidence():
    text = prediction_message(record())
    assert '2/3' in text
    assert 'AI Güveni' not in text
    assert 'Penaltı' not in text


def test_split_message_distribution():
    r = record()
    r['ai_votes'][1] = vote('b','3-1')
    r['consensus'] = build_consensus([AIVote(**v) for v in r['ai_votes']])
    assert 'Ortak tahmin' in prediction_message(r) and 'Yok' in prediction_message(r)
    assert '2–1 | 1/3' in prediction_message(r)


def test_score_normalization():
    assert _normalize({'outcome':'HOME','score':'02 - 01','confidence':50},'h','a')['score'] == '2-1'


def test_corrupt_state_is_preserved(tmp_path):
    p = tmp_path/'state.json'
    p.write_text('{broken', encoding='utf-8')
    with pytest.raises(StateError):
        load_json(p, {})
    assert p.read_text() == '{broken'


def test_atomic_state_roundtrip(tmp_path):
    p = tmp_path/'state.json'
    save_json(p, {'x': 2})
    assert load_json(p,{}) == {'x':2}
    assert not p.with_suffix('.json.tmp').exists()


def test_delivery_resumes_after_partial_message():
    bot = FakeTelegram(fail_at=2)
    receipt = {}
    with pytest.raises(TelegramError):
        deliver_text(bot, '1', 'x'*4000, receipt, lambda:None)
    assert receipt['parts_sent'] == 1
    bot.fail_at=0
    deliver_text(bot,'1','x'*4000,receipt,lambda:None)
    assert len(bot.calls)==4
    assert receipt['complete']


def test_photo_failure_does_not_repeat_text(monkeypatch, tmp_path):
    import match_report
    monkeypatch.setattr(match_report,'render_match_group_image',lambda *a,**k:tmp_path/'x.png')
    r=record();r['image_required']=True
    bot=FakeTelegram(fail_at=99)
    with pytest.raises(TelegramError):
        deliver_record(r,bot,'1',lambda:None,clock=lambda:NOW)
    assert r['prediction_receipt']['complete']
    bot.fail_at=0
    deliver_record(r,bot,'1',lambda:None,clock=lambda:NOW)
    assert sum(x[0]=='sendMessage' for x in bot.calls)==1
    assert r['final_sent']


def test_late_delivery_never_sends_prediction():
    r=record();bot=FakeTelegram()
    deliver_record(r,bot,'1',lambda:None,clock=lambda:NOW+timedelta(hours=2))
    assert r['delivery_expired']
    assert bot.calls == []


def test_result_retry_without_new_result():
    r=record();r['final_sent']=True;r['actual']={'home':2,'away':1};grade_record(r)
    bot=FakeTelegram(fail_at=1)
    drain_delivery({'1':r},bot,'1',lambda:None)
    assert not r.get('result_sent')
    bot.fail_at=0
    drain_delivery({'1':r},bot,'1',lambda:None)
    assert not r.get('result_sent')
    assert bot.calls == []


def test_old_result_is_not_auto_migrated_during_refresh():
    r=record();r.update(final_sent=True,result_sent=True,grading_version=2,consensus_points=5,
                         actual={'home':2,'away':1,'status':'FINISHED','scope':'REGULAR_90'})
    before=copy.deepcopy(r)
    match={'id':1,'status':'FINISHED','score':{'duration':'REGULAR','fullTime':{'home':2,'away':1}}}
    refresh_results({'1':r},[match])
    assert r == before


def test_fallback_requires_data_and_is_separate():
    assert predict({}) is None
    form={'matches':[{}, {}, {}], 'avg_goals_for':1.5,'avg_goals_against':1.1}
    result=predict({'home':{'last_5':form},'away':{'last_5':form}})
    r=record();r.update(prediction_kind='STATISTICAL',fallback=result)
    text=prediction_message(r)
    assert 'Tahmin üretilemedi' in text
    assert 'AI Güveni' not in text
    assert 'Uzlaşma' not in text


def proposal(state):
    p={'id':'abc123','status':'PENDING','created_at':NOW.isoformat(),'base_revision':0,
       'previous_policy':'balanced_v1','policy':'lineup_caution_v1',
       'instruction':POLICIES['lineup_caution_v1'],'reason':'Test',
       'evidence':{'with_xi_matches':8,'without_xi_matches':8,'with_xi_any_exact_rate':.5,
                   'without_xi_any_exact_rate':.1,'match_ids':['1'],'limitation':'Gözlemsel'},
       'message_id':42,'notified':True}
    state['proposals'][p['id']]=p
    return p


def callback(p, action='approve', user=10):
    return {'id':'q1','from':{'id':user},'message':{'message_id':42,'chat':{'id':10,'type':'private'}},
            'data':f"{action}:{p['id']}:{fingerprint(p)}"}


def test_only_admin_can_approve_once():
    state=new_state();p=proposal(state)
    assert handle_callback(callback(p,user=11),state,10,10,NOW)=='Yetkisiz işlem.'
    assert state['revision']==0
    handle_callback(callback(p),state,10,10,NOW)
    assert state['policy']=='lineup_caution_v1'
    handle_callback(callback(p),state,10,10,NOW)
    assert state['revision']==1 and len(state['decisions'])==1


def test_details_and_rejection_never_apply():
    state=new_state();p=proposal(state)
    assert 'Maç kimlikleri' in handle_callback(callback(p,'detail'),state,10,10,NOW)
    assert state['revision']==0
    handle_callback(callback(p,'reject'),state,10,10,NOW)
    assert p['status']=='REJECTED' and state['policy']=='balanced_v1'


def test_tampered_or_stale_proposal_rejected():
    state=new_state();p=proposal(state);q=callback(p)
    p['instruction']='arbitrary new code'
    assert 'doğrulanamadı' in handle_callback(q,state,10,10,NOW)
    assert state['revision']==0
    p=proposal(state)
    handle_callback(callback(p),state,10,10,NOW+timedelta(days=8))
    assert p['status']=='STALE' and state['revision']==0


def test_poll_cursor_and_decision_are_saved_before_external_ack(monkeypatch):
    import operations
    monkeypatch.setattr(operations,'datetime',type('Clock',(),{'now':staticmethod(lambda tz:NOW),'fromisoformat':datetime.fromisoformat}))
    state=new_state();p=proposal(state)
    bot=FakeTelegram(updates=[{'update_id':8,'callback_query':callback(p)}])
    saved=[]
    run_operations(bot,state,lambda:saved.append(copy.deepcopy(state)),10,10)
    assert saved[0]['update_offset']==9
    assert saved[0]['policy']=='lineup_caution_v1'
    run_operations(bot,state,lambda:None,10,10)
    assert len(state['decisions'])==1


def test_no_future_results_in_learning():
    r=record();r['actual']={'home':2,'away':1,'updated_at':(NOW+timedelta(hours=3)).isoformat()}
    r['post_match_analysis']=audit(r)
    assert not eligible(r,NOW+timedelta(hours=2))
    assert learning_context({'1':r},new_state(),NOW+timedelta(hours=2))['historical_matches']==0
    assert eligible(r,NOW+timedelta(hours=4))


def test_too_little_evidence_never_proposes_or_changes_settings():
    r=record();r['actual']={'home':2,'away':1};r['post_match_analysis']=audit(r)
    state=new_state();maybe_propose({'1':r},state)
    assert not state['proposals'] and state['revision']==0


def test_missing_model_not_counted_as_wrong():
    r=record();r['actual']={'home':2,'away':1};r['post_match_analysis']=audit(r)
    model=summarize({'1':r})['models']['d']
    assert model['available']==0 and model['avg_points'] is None


def test_predicted_xi_excludes_unavailable_or_unverified_players():
    good={'name':'A','current_club_confirmed':True,'unavailable':False,'source_url':'https://club.test/lineup'}
    data={'predicted_xi':{'home':[good,dict(good,name='B',unavailable=True),dict(good,name='C',current_club_confirmed=False),good]}}
    assert predicted_xi(data)['home']==[good]
    assert not valid_xi([{'name':'same'}]*11)


def fixture():
    return {'id':1,'utcDate':(NOW+timedelta(minutes=30)).isoformat(),'status':'TIMED',
            'homeTeam':{'id':1,'name':'H'},'awayTeam':{'id':2,'name':'A'},'matchday':1}


def test_wait_for_official_until_30_then_finalize_without_ai(monkeypatch):
    import runner
    monkeypatch.setattr(runner,'now',lambda:NOW)
    monkeypatch.setattr(runner,'official_xi',lambda *a:None)
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    monkeypatch.setattr(runner,'prepare_context',lambda *a:{'home':{},'away':{}})
    monkeypatch.setattr(runner,'run_ai_pool',lambda *a,**k:[AIVote(**vote('a','0-0',False))])
    m=fixture();m['utcDate']=(NOW+timedelta(minutes=40)).isoformat()
    state=new_state();r=new_record(m,state)
    assert not prepare_prediction(r,m,None,{},state,lambda:None,float('inf'))
    m['utcDate']=(NOW+timedelta(minutes=30)).isoformat()
    assert prepare_prediction(r,m,None,{},state,lambda:None,float('inf'))
    assert r['prediction_kind']=='UNAVAILABLE'
    assert 'Tahmin üretilemedi' in r['prediction_text']


def test_saved_prediction_not_generated_again(monkeypatch):
    import runner
    monkeypatch.setattr(runner,'run_ai_pool',lambda *a,**k:pytest.fail('must not regenerate'))
    r=record()
    r['prediction_complete'] = True
    assert prepare_prediction(r,fixture(),None,{},new_state(),lambda:None,0)


def test_full_main_twice_does_not_regenerate_or_resend(monkeypatch, tmp_path):
    import runner
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'now', lambda: NOW)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '10')
    monkeypatch.delenv('TEST_MODE', raising=False)
    monkeypatch.delenv('OPERATIONS_TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    bot = FakeTelegram()
    monkeypatch.setattr(runner, 'Telegram', lambda token: bot)
    class Football:
        def __init__(self, *a): pass
        def get_matches(self): return [fixture()]
        def get_team_matches(self, *a): return []
        def get_standings(self): return []
    monkeypatch.setattr(runner, 'CachedFootball', Football)
    monkeypatch.setattr(runner, 'official_xi', lambda *a: None)
    count=[]
    def pool(*args, **kwargs):
        count.append(1)
        specs = [
            ('Gemini 3.6 Flash', '2-1'), ('Groq Qwen 3.8 27B', '2-1'),
            ('Cohere Command A+', '2-1'), ('Groq GPT-OSS 120B', '1-1'),
            ('Cloudflare Clef-omni', '1-1'),
        ]
        votes = [AIVote(**vote(name, score)) for name, score in specs]
        for item in votes:
            kwargs['on_vote'](item)
        return votes
    monkeypatch.setattr(runner, 'run_ai_pool', pool)
    assert runner.main() == 0
    assert runner.main() == 0
    assert len(count) == 1
    assert sum(method == 'sendMessage' for method, _ in bot.calls) == 0
    assert sum(method == 'photo' for method, _ in bot.calls) == 1
    saved=load_json(tmp_path/'match_predictions.json',{})['1']
    assert saved['final_sent'] and saved['prediction_kind']=='AI'
    assert saved['prediction_complete'] is True
    assert saved['consensus_status'] == 'FINAL'
    assert saved['model_versions'] and saved['input_hash']
    assert saved['consensus']['winner_consensus'] is True


def test_official_lineup_reads_v4_team_nodes():
    from providers import official_xi
    h = [{'name':f'Home {i}'} for i in range(11)]
    a = [{'name':f'Away {i}'} for i in range(11)]
    class Football:
        def get_match_details(self, _): return {'homeTeam':{'lineup':h},'awayTeam':{'lineup':a}}
    result=official_xi(Football(),fixture())
    assert result['home']==h and result['away']==a and result['status']=='ANNOUNCED'


def test_prompt_keeps_eleven_players():
    players=[{'name':f'Player_{i:02d}'} for i in range(11)]
    prompt=build_prompt('A','B',{'official_xi':{'home':players,'away':players}}, {}, {})
    assert 'Player_10' in prompt


def test_proposal_requires_evidence_and_stays_pending():
    rows={}
    for i in range(16):
        r=record()
        r['match_id']=str(i)
        r['context']['official_xi']['status']='ANNOUNCED' if i<8 else 'NOT_ANNOUNCED'
        r['actual']={'home':2 if i<8 else 5,'away':1,'updated_at':(NOW+timedelta(hours=3)).isoformat()}
        r['post_match_analysis']=audit(r)
        rows[str(i)]=r
    state=new_state();maybe_propose(rows,state)
    assert len(state['proposals'])==1
    assert next(iter(state['proposals'].values()))['status']=='PENDING'
    assert state['policy']=='balanced_v1' and state['revision']==0
    maybe_propose(rows,state)
    assert len(state['proposals'])==1


def test_finished_extra_time_without_regular_score_never_regrades():
    r=record()
    refresh_results({'1':r},[{'id':1,'status':'FINISHED','score':{'duration':'EXTRA_TIME','fullTime':{'home':3,'away':2}}}])
    assert not r.get('actual')
    assert '90 dakika' in r['result_warning']


def test_result_correction_requires_review_and_preserves_receipts():
    r=record();r.update(actual={'home':2,'away':1,'status':'FINISHED','scope':'REGULAR_90'},
                       grading_version=VERSION,result_sent=True,result_text='old',result_receipt={'complete':True})
    original=copy.deepcopy(r)
    new=[{'id':1,'status':'FINISHED','score':{'duration':'REGULAR','fullTime':{'home':2,'away':2}}}]
    refresh_results({'1':r},new)
    pending=r.pop('result_correction_pending_review')
    assert r == original
    assert pending['proposed_actual']['home'] == 2
    assert pending['proposed_actual']['away'] == 2
    r['result_correction_pending_review']=pending
    snapshot=copy.deepcopy(r)
    refresh_results({'1':r},new)
    assert r == snapshot


def test_rollback_is_proposed_not_applied():
    rows={}
    for i in range(16):
        r=record();r['match_id']=str(i)
        r['learning_policy']='balanced_v1' if i<8 else 'lineup_caution_v1'
        r['policy_revision']=0 if i<8 else 1
        r['actual']={'home':2 if i<8 else 5,'away':1}
        r['post_match_analysis']=audit(r)
        rows[str(i)]=r
    state=new_state();state.update(policy='lineup_caution_v1',revision=1)
    maybe_propose(rows,state)
    assert len(state['proposals'])==1
    p=next(iter(state['proposals'].values()))
    assert p['policy']=='balanced_v1' and p['status']=='PENDING'
    assert state['policy']=='lineup_caution_v1' and state['revision']==1


def test_partial_prediction_is_marked_provisional_and_keeps_individual_votes():
    from messages import prediction_tables
    r = record()
    r['ai_votes'][2]['result'].update(score='3-1', outcome='HOME')
    r['prediction_complete'] = False
    table = prediction_tables(r)
    assert 'GEÇİCİ ORTAK KARAR' in table['note']
    assert '3/5' in table['note']
    assert len(table['rows']) >= 1


def test_prediction_update_notification_is_resumable_and_not_duplicated():
    import runner
    r = record()
    r.update(final_sent=True, prediction_ready=True, prediction_complete=False,
             prediction_update_required=True, prediction_text='Güncel 3/5 tahminler')
    bot = FakeTelegram()
    saves=[]
    runner.drain_prediction_updates({'1': r}, bot, '10', lambda: saves.append(1))
    assert not r['prediction_update_required']
    assert r['published_successful_ai'] == 3
    assert r['published_prediction_complete'] is False
    sent_before = sum(method == 'sendMessage' for method, _ in bot.calls)
    runner.drain_prediction_updates({'1': r}, bot, '10', lambda: saves.append(1))
    assert sum(method == 'sendMessage' for method, _ in bot.calls) == sent_before


def test_pool_resumes_cached_votes_without_calling_provider(monkeypatch):
    import ai_pool
    calls=[]
    monkeypatch.setenv('GEMINI_API_KEY','test')
    monkeypatch.setattr(ai_pool,'_gemini',lambda p:calls.append('gemini') or '{"outcome":"HOME","score":"2-1","confidence":70}')
    for env in ('GROQ_API_KEY','COHERE_API_KEY','CLOUDFLARE_API_TOKEN'):
        monkeypatch.delenv(env,raising=False)
    saved=[]
    votes=ai_pool.run_ai_pool('h','a',{}, {}, {},on_vote=saved.append)
    assert sum(v.success for v in votes)==1 and len(saved)==5
    cached={v.model:{'model':v.model,'success':v.success,'result':v.result,'error':v.error} for v in votes}
    ai_pool.run_ai_pool('h','a',{}, {}, {},cached=cached)
    assert calls==['gemini']


def test_factors_are_audited_without_inventing_legacy_labels():
    from learning import factor_summary
    r=record();r['actual']={'home':2,'away':1};r['post_match_analysis']=audit(r)
    assert factor_summary({'1':r})['a:form']['exact']==1
    for v in r['ai_votes']:
        if v.get('result'): v['result'].pop('factors_used',None)
    r['post_match_analysis']=audit(r)
    assert factor_summary({'1':r})=={}
