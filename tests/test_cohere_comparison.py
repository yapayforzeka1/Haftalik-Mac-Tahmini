import json
import httpx
import pytest
import diagnose_cohere as diag


def response_data(score='1-0',finish='COMPLETE'):
    return {'finish_reason':finish,'message':{'content':[{'type':'text','text':json.dumps(
        {'outcome':'HOME','score':score,'confidence':60,'short_reason':'Test sebebi', 'reasons':['Test sebebi']})}]}}


@pytest.mark.parametrize('body,expected',[
    (response_data(),'VALID_PREDICTION'),
    (response_data('0-1'),'INVALID_PREDICTION'),
    (response_data(finish='MAX_TOKENS'),'RESPONSE_TRUNCATED'),
    ({'finish_reason':'COMPLETE','message':{'content':[{'type':'thinking','thinking':'private'}]}},'INVALID_JSON'),
    ([], 'INVALID_RESPONSE')])
def test_validation(body,expected):
    assert diag.validate_response(body)==expected


def test_two_variants_and_safe_logs(monkeypatch,capsys):
    monkeypatch.setenv('COHERE_API_KEY','private-api-key')
    calls=[]
    class Client:
        def post(self,url,**kwargs):
            assert url=='https://api.cohere.com/v2/chat'
            calls.append(kwargs['json'])
            if len(calls)==1:
                return httpx.Response(422,json={'message':'invalid tool generation private-api-key'})
            return httpx.Response(200,json=response_data())
    diag.run(Client())
    assert len(calls)==2
    assert calls[0]['messages']==calls[1]['messages']
    assert 'thinking' not in calls[0]
    assert calls[0]['response_format']=={'type':'json_object'}
    assert 'response_format' not in calls[1]
    assert calls[1]['thinking']=={'type':'disabled'}
    output=capsys.readouterr().out
    assert 'private-api-key' not in output and 'VALID_PREDICTION' in output
    assert 'Test sebebi' not in output


@pytest.mark.parametrize('status',[401,403,429])
def test_no_extra_call_after_auth_or_limit(monkeypatch,status):
    monkeypatch.setenv('COHERE_API_KEY','test-key')
    calls=[]
    class Client:
        def post(self,*args,**kwargs):
            calls.append(1)
            return httpx.Response(status,json={'message':'failed'})
    diag.run(Client())
    assert len(calls)==1


def test_missing_key(monkeypatch,capsys):
    monkeypatch.delenv('COHERE_API_KEY',raising=False)
    diag.run(None)
    assert 'MISSING_API_KEY' in capsys.readouterr().out
