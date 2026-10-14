import ast
import copy
from pathlib import Path
import pytest
from learning import new_state, POLICIES
from policy_sync import apply_approved_policy
from storage import save_json, StateError
from runner import refresh_results, drain_delivery


def test_no_operations_dispatch_in_main():
    tree=ast.parse(Path('runner.py').read_text(encoding='utf-8'))
    calls=[n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
    assert 'run_operations' not in calls and 'maybe_propose' not in calls


def test_approved_policy_validation(tmp_path):
    state=new_state();path=tmp_path/'policy.json'
    doc={'schema':1,'policy':'lineup_caution_v1','revision':1,'instruction':POLICIES['lineup_caution_v1']}
    save_json(path,doc);apply_approved_policy(state,str(path))
    assert state['revision']==1
    doc['instruction']='arbitrary code';save_json(path,doc)
    with pytest.raises(StateError):apply_approved_policy(state,str(path))
    assert state['revision']==1


def test_results_recorded_without_telegram():
    record={'match_id':'1','final_sent':True,'prediction_ready':True,'ai_votes':[
        {'model':'A','success':True,'result':{'outcome':'HOME','score':'2-1','confidence':60,'reasons':[]}}],
        'consensus':{},'context':{}}
    predictions={'1':record}
    refresh_results(predictions,[{'id':1,'status':'FINISHED','score':{'duration':'REGULAR','fullTime':{'home':2,'away':1}}}])
    assert record['actual']['home']==2 and record['ai_votes'][0]['points']==8
    class Bot:
        def call(self,*a,**k):pytest.fail('Result sent')
        def photo(self,*a,**k):pytest.fail('Result image sent')
    drain_delivery(predictions,Bot(),'chat',lambda:None)
    snapshot=copy.deepcopy(predictions)
    refresh_results(predictions,[{'id':1,'status':'FINISHED','score':{'duration':'REGULAR','fullTime':{'home':2,'away':1}}}])
    assert predictions==snapshot
