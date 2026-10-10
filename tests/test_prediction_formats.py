import copy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from ai_pool import AIVote, _normalize
from consensus_engine import build_consensus
from history_engine import grade_record
from messages import prediction_tables, short_reason
from runner import deliver_record
from telegram_io import TelegramError

NAMES = ['Gemini 3.6 Flash','Mistral Small Latest','Groq Qwen 3.6 27B','Cohere Command A+','Groq GPT-OSS 120B']


def example(scores):
    votes = []
    for name, score in zip(NAMES, scores):
        if score is None:
            votes.append(AIVote(name,False,error='TIMEOUT'))
            continue
        h,a = map(int,score.split('-'))
        votes.append(AIVote(name,True,{'outcome':'HOME' if h>a else 'AWAY' if a>h else 'DRAW',
            'score':score,'confidence':60,'reasons':['Ayrıntılı model gerekçesi korunur.'],
            'short_reason':'İç saha formu etkili.'}))
    r = {'match_id':'test','home_team':'Sporting','away_team':'Galatasaray','match_utc':'2030-09-18T19:00:00Z',
         'context':{'official_xi':{'status':'ANNOUNCED'}}, 'ai_votes':[asdict(v) for v in votes],
         'consensus_min_successful':3,'prediction_kind':'AI' if any(v.success for v in votes) else 'UNAVAILABLE'}
    if any(v.success for v in votes):
        r['consensus'] = build_consensus(votes,min_successful=3)
    return r


@pytest.mark.parametrize('scores,mode,rows',[
    (['1-2','1-2','1-2','0-1','1-1'],'NORMAL',0),
    (['0-1','1-2','0-1','1-3','2-0'],'OUTCOME_COMMON_SCORE_SPLIT',4),
    (['1-0','0-1','1-1','2-1','0-1'],'NO_COMMON',5),
    (['1-2','2-1',None,None,None],'INDIVIDUAL',2),
    (['1-2',None,None,None,None],'INDIVIDUAL',1),
    ([None]*5,'UNAVAILABLE',0),
])
def test_five_formats_preserve_votes(scores,mode,rows):
    r=example(scores); original=copy.deepcopy(r)
    table=prediction_tables(r)
    assert table['mode']==mode and len(table['rows'])==rows
    assert table['summary'][1]=='22:00 TSİ'
    assert r==original
    if mode=='UNAVAILABLE':
        assert table['summary'][2:] == ['0/5','⚠️ Tahmin üretilemedi']
        assert not table['note']


def test_models_grouped_in_approved_column_order():
    t=prediction_tables(example(['0-1','1-2','0-1','1-3','2-0']))
    assert t['headers']==['🤖 AI Modelleri','🎯 Skor','Oy']
    assert t['rows'][0]==['Gemini, Qwen','0–1','2/5']


def test_no_common_has_correct_team_reason_and_repeated_score_votes():
    t=prediction_tables(example(['1-0','0-1','1-1','2-1','0-1']))
    assert t['rows'][1][1].startswith('Galatasaray — ')
    assert t['rows'][1][3]==t['rows'][4][3]=='2/5'
    assert t['rows'][2][1].startswith('Beraberlik — ')


def test_two_agreeing_models_remain_individual_in_new_archive():
    r=example(['1-2','1-2',None,None,None])
    assert r['consensus']['outcome'] is None
    assert prediction_tables(r)['mode']=='INDIVIDUAL'
    r['actual']={'home':1,'away':2}
    grade_record(r)
    assert r['consensus_points'] is None
    assert r['ai_votes'][0]['points']==6
    # Fixed three-vote rule applies even when older metadata is absent.
    r.pop('consensus_min_successful');r['consensus'].pop('min_successful')
    grade_record(r)
    assert r['consensus_points'] is None


def test_reason_saved_without_losing_full_explanation():
    raw={'outcome':'HOME','score':'2-1','confidence':60,'short_reason':'İç saha avantajı.',
         'reasons':['Uzun gerekçe korunmalı.']}
    result=_normalize(raw,'h','a')
    assert result['reasons']==raw['reasons'] and short_reason(result)==raw['short_reason']
    assert short_reason({})=='Gerekçe belirtilmedi.'
    with pytest.raises(ValueError):
        _normalize(dict(raw,outcome='AWAY'),'h','a')


@pytest.mark.parametrize('status,expected',[(None,'⚠️ Kadro eksik'),('ANNOUNCED','✅ Resmî 11')])
def test_lineup_status(status,expected):
    r=example(['1-2']*5);r['context']['official_xi']['status']=status
    assert prediction_tables(r)['summary'][2]==expected
    if status is None:
        r['context']['predicted_xi']={'home':[{}]*11,'away':[{}]*11}
        assert prediction_tables(r)['summary'][2]=='⚠️ Tahmini 11'


def test_image_delivery_retry_is_single_message_and_never_regenerates(monkeypatch,tmp_path):
    import match_report
    monkeypatch.setattr(match_report,'render_match_group_image',lambda *a,**k:tmp_path/'preview.png')
    r=example(['1-2']*5)
    r.update(prediction_ready=True,message_format_version=4,prediction_table=prediction_tables(r))
    before=datetime(2030,9,18,18,tzinfo=timezone.utc)
    class Bot:
        fail=True
        photos=0
        def photo(self,*args):
            if self.fail: raise TelegramError('test')
            self.photos+=1
        def call(self,*args,**kwargs): pytest.fail('No duplicate text')
    bot=Bot()
    with pytest.raises(TelegramError): deliver_record(r,bot,'1',lambda:None,clock=lambda:before)
    assert not r.get('final_sent')
    bot.fail=False
    deliver_record(r,bot,'1',lambda:None,clock=lambda:before)
    deliver_record(r,bot,'1',lambda:None,clock=lambda:before)
    assert bot.photos==1 and r['prediction_receipt']['complete']


def test_no_photo_when_render_finishes_after_kickoff(monkeypatch,tmp_path):
    import match_report
    monkeypatch.setattr(match_report,'render_match_group_image',lambda *a,**k:tmp_path/'x.png')
    r=example(['1-2']*5);r.update(prediction_ready=True,message_format_version=4)
    kickoff=datetime(2030,9,18,19,tzinfo=timezone.utc)
    times=iter([kickoff-timedelta(seconds=1),kickoff])
    calls=[]
    class Bot:
        def photo(self,*args): pytest.fail('Late prediction')
        def call(self,*args,**kwargs): calls.append(kwargs);return {'message_id':1}
    deliver_record(r,Bot(),'1',lambda:None,clock=lambda:next(times))
    assert r['delivery_expired'] and calls == []


def test_render_all_modes_and_long_names(tmp_path,monkeypatch):
    import match_report
    from PIL import Image
    monkeypatch.setattr(match_report,'REPORT_DIR',tmp_path)
    for scores in (['1-2']*5,['0-1','1-2','0-1','1-3','2-0'],['1-0','0-1','1-1','2-1','0-1'],
                   ['1-2',None,None,None,None],[None]*5):
        r=example(scores)
        r['home_team']='Sporting Clube de Portugal';r['away_team']='Club Atlético de Madrid'
        path=match_report.render_match_group_image([r])
        with Image.open(path) as im:
            assert im.width==900 and 150<im.height<3000
