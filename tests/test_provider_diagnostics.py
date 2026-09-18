import json
import httpx
import diagnose_providers as diag


def setup_keys(monkeypatch):
    for name in ('GEMINI', 'MISTRAL', 'COHERE'):
        monkeypatch.setenv(name+'_API_KEY', name+'-private-key')


def test_diagnostic_four_requests_no_retries(monkeypatch,capsys):
    setup_keys(monkeypatch)
    requests=[]
    def handler(request):
        requests.append(request)
        if 'mistral' in request.url.host:
            return httpx.Response(429,json={'message':'token rate limit'},headers={'retry-after':'60'})
        if len(requests)==4:
            return httpx.Response(422,json={'detail':[{'loc':['body','thinking'],'msg':'Unsupported parameter'}]})
        return httpx.Response(200,json={})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        # The suite blocks Client.send; use the normal implementation only with MockTransport.
        monkeypatch.setattr(client,'post',lambda url,headers,json: handler(httpx.Request('POST',url,headers=headers,json=json)))
        diag.run(client)
    assert len(requests)==4
    assert all('groq' not in str(r.url) and 'telegram' not in str(r.url) for r in requests)
    body=json.loads(requests[-1].content)
    assert body['response_format']=={'type':'json_object'}
    output=capsys.readouterr().out
    assert 'HTTP=422' in output and 'body/thinking' in output
    assert 'Retry-After=60' in output
    assert 'private-key' not in output


def test_failed_basic_skips_cohere_prediction(monkeypatch,capsys):
    setup_keys(monkeypatch)
    calls=[]
    class Client:
        def post(self,url,**kwargs):
            calls.append(url)
            return httpx.Response(422,json={'message':'not available'})
    diag.run(Client())
    assert len(calls)==3
    assert 'SKIPPED_BASIC_FAILED' in capsys.readouterr().out


def test_redaction_and_workflow_command_injection(monkeypatch):
    monkeypatch.setenv('COHERE_API_KEY','secret-value-123')
    response=httpx.Response(422,json={'message':'secret-value-123 Bearer unknown-secret https://example.com/?key=secret\n::warning::bad',
                                    'request':{'private':'must-not-print'}})
    text=diag.error_description(response)
    assert 'secret-value-123' not in text and 'unknown-secret' not in text
    assert 'example.com' not in text and 'must-not-print' not in text
    assert '\n' not in text


def test_non_json_error_body_is_not_dumped():
    assert diag.error_description(httpx.Response(503,text='private html'))=='NON_JSON_ERROR_BODY'


def test_missing_keys_make_no_requests(monkeypatch,capsys):
    for name in ('GEMINI','MISTRAL','COHERE'):
        monkeypatch.delenv(name+'_API_KEY',raising=False)
    diag.run(None)
    assert capsys.readouterr().out.count('MISSING_API_KEY')==3
