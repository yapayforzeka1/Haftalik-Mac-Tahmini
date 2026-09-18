import json
from types import SimpleNamespace as NS

import pytest

import ai_pool as pool


class HTTPError(Exception):
    def __init__(self, status, retry=None):
        self.status_code = status
        self.response = NS(headers={'Retry-After':str(retry)} if retry is not None else {})
        super().__init__('private-token private-provider-body')


@pytest.fixture
def clock(monkeypatch):
    current=[0.0];waits=[]
    def sleep(seconds):
        waits.append(seconds);current[0]+=seconds
    monkeypatch.setattr(pool.time,'monotonic',lambda:current[0])
    monkeypatch.setattr(pool.time,'sleep',sleep)
    monkeypatch.setattr(pool.random,'uniform',lambda *args:0)
    return current,waits


@pytest.mark.parametrize('status', [429,503,502,500,504,408])
def test_transient_retry_then_success(status,clock):
    attempts=[]
    def request():
        attempts.append(1)
        if len(attempts)<3:raise HTTPError(status)
        return 'ok'
    assert pool._call_with_retry('test',request,deadline=200)=='ok'
    assert len(attempts)==3
    assert clock[1]==([20,40] if status==429 else [10,20])


@pytest.mark.parametrize('status', [400,401,403,404,422])
def test_permanent_errors_never_retry(status,clock):
    attempts=[]
    def request():
        attempts.append(1);raise HTTPError(status)
    with pytest.raises(HTTPError):pool._call_with_retry('test',request,deadline=200)
    assert len(attempts)==1 and not clock[1]


def test_retry_after_obeyed(clock):
    attempts=[]
    def request():
        attempts.append(1)
        if len(attempts)==1:raise HTTPError(429,45)
        return 'ok'
    assert pool._call_with_retry('test',request,deadline=200)=='ok'
    assert clock[1]==[45]


@pytest.mark.parametrize('delay,deadline',[(120,500),(45,60)])
def test_no_early_retry_when_wait_exceeds_budget(delay,deadline,clock):
    attempts=[]
    def request():
        attempts.append(1);raise HTTPError(429,delay)
    with pytest.raises(HTTPError):pool._call_with_retry('test',request,deadline=deadline)
    assert attempts==[1] and not clock[1]


def test_no_request_if_insufficient_time(clock):
    with pytest.raises(pool.TimeBudgetError):
        pool._call_with_retry('test',lambda:pytest.fail('late request'),deadline=20)


def test_date_and_sdk_retry_headers():
    from email.utils import format_datetime
    from datetime import datetime,timezone,timedelta
    date=format_datetime(datetime.now(timezone.utc)+timedelta(seconds=50))
    e=NS(raw_response=NS(status_code=429,headers={'retry-after':date}))
    assert pool.error_http_status(e)==429
    assert 48<=pool.retry_after_seconds(e)<=50
    assert pool.retry_after_seconds(NS(headers={'retry-after':'not-a-date'})) is None
    assert pool.retry_after_seconds(NS(headers={'retry-after':'inf'})) is None


def test_model_migration_preserves_custom_override():
    assert pool.resolve_qwen_model('qwen/qwen3.6-27b')=='qwen/qwen3.8-27b'
    assert pool.resolve_qwen_model('')=='qwen/qwen3.8-27b'
    assert pool.resolve_qwen_model('qwen/custom')=='qwen/custom'


def test_cohere_real_sdk_serializes_json_mode_without_thinking_override(monkeypatch):
    import httpx
    monkeypatch.setenv('COHERE_API_KEY','test-only')
    monkeypatch.setattr(pool,'COHERE_MODEL','command-a-plus-05-2026')
    requests=[]
    def send(client,request,**kwargs):
        body=json.loads(request.content);requests.append(body)
        return httpx.Response(200,request=request,json={'id':'test','finish_reason':'COMPLETE',
            'message':{'role':'assistant','content':[{'type':'text','text':'{"outcome":"AWAY","score":"1-2","confidence":60}'}]}})
    monkeypatch.setattr(httpx.Client,'send',send)
    text=pool._cohere('Return JSON')
    body=requests[0]
    assert body['response_format']['type']=='json_object'
    assert body['response_format']=={'type':'json_object'}
    assert 'thinking' not in body and body['max_tokens']==2048
    assert pool._normalize(pool._extract_json(text),'h','a')['score']=='1-2'


@pytest.mark.parametrize('finish,content,code',[
    ('MAX_TOKENS',[{'type':'text','text':'{"score":'}],'RESPONSE_TRUNCATED'),
    ('COMPLETE',[{'type':'thinking','thinking':'private reasoning'}],'EMPTY_RESPONSE'),
    ('ERROR',[],'RESPONSE_STOPPED')])
def test_cohere_distinguishes_truncation_and_empty(monkeypatch,finish,content,code):
    import cohere
    monkeypatch.setenv('COHERE_API_KEY','test-only')
    monkeypatch.setattr(cohere,'ClientV2',lambda **k:NS(chat=lambda **k:NS(finish_reason=finish,message=NS(content=content))))
    with pytest.raises(pool.OutputError,match=code):pool._cohere('prompt')


def test_partial_success_still_retries_failed_providers_and_saves_once(monkeypatch,clock):
    for env in ('GEMINI_API_KEY','MISTRAL_API_KEY','GROQ_API_KEY','COHERE_API_KEY'):
        monkeypatch.setenv(env,'private-key')
    good='{"outcome":"HOME","score":"1-0","confidence":65}'
    calls={'gemini':0,'mistral':0,'cohere':0}
    def gemini(_):
        calls['gemini']+=1
        if calls['gemini']==1:raise HTTPError(503)
        return good
    def mistral(_):
        calls['mistral']+=1
        if calls['mistral']==1:raise HTTPError(429)
        return good
    def cohere(_):
        calls['cohere']+=1
        return 'not JSON' if calls['cohere']==1 else good
    monkeypatch.setattr(pool,'_gemini',gemini);monkeypatch.setattr(pool,'_mistral',mistral)
    monkeypatch.setattr(pool,'_cohere',cohere);monkeypatch.setattr(pool,'_groq',lambda p,m:good)
    saved=[]
    votes=pool.run_ai_pool('h','a',{}, {}, {},on_vote=saved.append,deadline=500)
    assert all(v.success for v in votes) and len(saved)==5
    assert calls=={'gemini':2,'mistral':2,'cohere':2}
    assert pool.QWEN_LABEL in [v.model for v in votes]
    assert next(v for v in votes if v.model==pool.QWEN_LABEL).result['model_id']==pool.GROQ_QWEN_MODEL


def test_invalid_json_only_retried_once(clock):
    calls=[]
    def request():
        calls.append(1);return pool._extract_json('{unfinished')
    with pytest.raises(pool.OutputError,match='INVALID_JSON'):
        pool._call_with_retry('test',request,deadline=200)
    assert len(calls)==2


def test_json_fences_supported_but_truncated_or_ambiguous_output_rejected():
    assert pool._extract_json('```json\n{"score":"1-2"}\n```')=={'score':'1-2'}
    with pytest.raises(pool.OutputError):pool._extract_json('{"score":"1-2"} {"score":"2-1"}')
    with pytest.raises(ValueError):pool._normalize([], 'h','a')


def test_mistral_waits_full_minute(clock):
    calls=[]
    def request():
        calls.append(1)
        if len(calls)==1: raise HTTPError(429)
        return 'ok'
    assert pool._call_with_retry('Mistral Small Latest',request,deadline=200)=='ok'
    assert clock[1]==[60]


def test_mistral_does_not_retry_past_delivery_deadline(clock):
    calls=[]
    def request():
        calls.append(1);raise HTTPError(429)
    with pytest.raises(HTTPError):
        pool._call_with_retry('Mistral Small Latest',request,deadline=80)
    assert len(calls)==1 and clock[1]==[]


@pytest.mark.parametrize('body,expected',[
    ({'message':'tokens per minute exceeded secret-key'},'TOKEN_RATE_LIMIT'),
    ('requests per second exceeded secret-key','REQUEST_RATE_LIMIT'),
    ({'error':{'code':'insufficient_quota'}},'QUOTA_EXHAUSTED'),
    ('unknown private-body','LIMIT_UNSPECIFIED')])
def test_rate_details_are_fixed_codes(body,expected):
    error=HTTPError(429);error.body=body
    assert pool.safe_error_detail(error)==expected


def test_exhausted_quota_not_retried(clock):
    calls=[]
    def request():
        calls.append(1)
        error=HTTPError(429);error.body={'code':'insufficient_quota'}
        raise error
    with pytest.raises(HTTPError):pool._call_with_retry('Mistral Small Latest',request)
    assert calls==[1] and clock[1]==[]


def test_invalid_request_details_do_not_expose_body():
    error=HTTPError(422);error.body={'message':'thinking is unsupported private-key'}
    assert pool.safe_error_detail(error)=='CHECK_THINKING'
    error.body={'message':'private-key unknown field'}
    assert pool.safe_error_detail(error)=='REQUEST_DETAIL_UNSPECIFIED'
