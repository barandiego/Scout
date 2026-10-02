"""Exercise the real AIClient and SDK against an offline HTTP transport."""
import copy
import json
import shutil
import pytest
from openai import OpenAI
import httpx2 as httpx
from scout import pipeline
from scout.runtime import AIClient, AIResponseError, _parse_json, _collect_urls
from test_integration import DISCOVERY
from scout.state import Store

SOURCES = ['https://primary.example/a', 'https://independent.example/b']
CRITIC = {'fatal': False, 'critic_case': 'No fatal contradiction found.',
          'contrary_evidence': [], 'unknowns': [], 'falsification_conditions': [],
          'evidence_confidence': .75}
JUDGE = {'status': 'survived', 'vertical_fatal': False,
         'decision_reason': 'Evidence supports HQ review.', 'judgment_confidence': .7,
         'major_risks': [], 'unknowns': []}

def response_body(request, text, *, status='completed', sources=SOURCES, incomplete_reason=None):
    output = []
    if 'tools' in request:
        output.append({'id': 'ws_test', 'type': 'web_search_call', 'status': 'completed',
                       'action': {'type': 'search', 'query': 'test', 'sources':
                                  [{'type': 'url', 'url': url} for url in sources]}})
    output.append({'id': 'msg_test', 'type': 'message', 'status': 'completed',
                   'role': 'assistant', 'content': [
                       {'type': 'output_text', 'text': text, 'annotations': []}]})
    return {'id': 'resp_test', 'object': 'response', 'created_at': 1,
            'model': request['model'], 'status': status, 'output': output,
            'incomplete_details': ({'reason': incomplete_reason or 'max_output_tokens'} if status == 'incomplete' else None),
            'usage': {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150,
                      'input_tokens_details': {'cached_tokens': 20},
                      'output_tokens_details': {'reasoning_tokens': 0}}}

def offline_client(monkeypatch, handler):
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-test-key')
    ai = AIClient(pipeline.load_yaml(pipeline.ROOT/'config'/'scout.yaml')['pricing'])
    assert ai.client.max_retries == 0
    assert ai.client.timeout == 60.0
    ai.client.close()
    ai.client = OpenAI(api_key='offline-test-key', max_retries=0,
                       http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return ai

def isolated_cycle(tmp_path, monkeypatch):
    shutil.copytree(pipeline.ROOT/'config', tmp_path/'config')
    monkeypatch.setattr(pipeline, 'ROOT', tmp_path)

def research(ai, web=True):
    return ai.json_research(model='gpt-5.6-luna', instructions='Return JSON.',
                            prompt='Return a JSON object.', max_output_tokens=2600,
                            web_search=web, max_tool_calls=2 if web else 0)

def assert_contract(req):
    assert req['store'] is False
    assert req['reasoning'] == {'effort': 'low'}
    if 'tools' in req:
        # Reproduce run #3's server-side rejection at the real SDK boundary.
        assert 'text' not in req
        assert req['tools'] == [{'type': 'web_search', 'search_context_size': 'low'}]
        assert req['max_tool_calls'] == 2
        assert req['tool_choice'] == 'required'
        assert req['include'] == ['web_search_call.action.sources']
        assert 'exactly one JSON object' in req['instructions']
    else:
        assert req['text'] == {'format': {'type': 'json_object'}}
        assert 'JSON' in req['instructions'] + req['input']
        assert 'max_tool_calls' not in req
        assert 'include' not in req

@pytest.mark.parametrize('stage,text,status,sources,expected', [
    ('discovery', None, 'completed', SOURCES, 'SUCCESS'),
    ('discovery', '{"candidates":[]}', 'completed', [], 'SUCCESS'),
    ('discovery', '{"candidates":', 'completed', SOURCES, 'DEGRADED_SUCCESS'),
    ('discovery', '{"candidates":[]}', 'incomplete', SOURCES, 'DEGRADED_SUCCESS'),
    ('discovery', '', 'completed', SOURCES, 'DEGRADED_SUCCESS'),
    ('discovery', '[]', 'completed', SOURCES, 'DEGRADED_SUCCESS'),
    ('discovery', None, 'failed', SOURCES, 'FAILED_INFRASTRUCTURE'),
    ('discovery', None, 'completed', [], 'SUCCESS'),
    ('critic', '{}', 'completed', SOURCES, 'DEGRADED_SUCCESS'),
    ('critic', '{"fatal":', 'completed', SOURCES, 'DEGRADED_SUCCESS'),
    ('critic', None, 'completed', [], 'DEGRADED_SUCCESS'),
    ('judge', '{}', 'completed', SOURCES, 'DEGRADED_SUCCESS'),
    ('judge', '', 'incomplete', SOURCES, 'DEGRADED_SUCCESS'),
])
def test_real_sdk_pipeline_matrix(tmp_path, monkeypatch, stage, text, status, sources, expected):
    isolated_cycle(tmp_path, monkeypatch)
    calls=[]
    def handler(request):
        req=json.loads(request.content); calls.append(req); assert_contract(req)
        current=('discovery' if 'Scout Discovery' in req['instructions'] else 'critic' if 'adversarial' in req['instructions'] else 'judge')
        data={'discovery':{'candidates':[DISCOVERY]},'critic':CRITIC,'judge':JUDGE}[current]
        return httpx.Response(200,json=response_body(req,
            text if current==stage and text is not None else json.dumps(data),
            status=status if current==stage else 'completed', sources=sources if current==stage else SOURCES))
    ai=offline_client(monkeypatch,handler)
    monkeypatch.setattr(pipeline,'AIClient',lambda _:ai)
    try: rec=pipeline.run_cycle()
    finally: ai.client.close()
    assert rec.outcome==expected and rec.ok==(expected!='FAILED_INFRASTRUCTURE')
    assert len(rec.usages)==len(calls)
    assert rec.cost_usd==pytest.approx(sum(u.estimated_cost_usd for u in rec.usages))
    assert Store(tmp_path).runs()[-1]['cost_usd']==rec.cost_usd
    assert (tmp_path/'reports/latest.md').exists()
    if status!='completed' or text is not None or not sources:
        assert rec.survivors==0
    else:
        assert rec.survivors==1
        assert rec.cost_usd==pytest.approx(.0209168)


@pytest.mark.parametrize('variant', ['exception','timeout','usage_missing','usage_bad','incomplete_other','tool_only','future_fields','refusal','partial_message'])
def test_response_edge_shapes(tmp_path,monkeypatch,variant):
    isolated_cycle(tmp_path,monkeypatch)
    def handler(request):
        if variant=='timeout': raise httpx.ReadTimeout('sensitive text',request=request)
        if variant=='exception': return httpx.Response(401,json={'error':{'message':'secret','type':'auth'}})
        req=json.loads(request.content)
        body=response_body(req,'{"candidates":[]}',status='incomplete' if variant=='incomplete_other' else 'completed',incomplete_reason='content_filter')
        if variant=='usage_missing': body.pop('usage')
        if variant=='usage_bad': body['usage']['input_tokens']='nonsense'
        if variant=='tool_only': body['output']=body['output'][:1]
        if variant=='future_fields': body['new_field']={'anything':[]}
        if variant=='refusal': body['output'][-1]['content'].append({'type':'refusal','refusal':'not provided'})
        if variant=='partial_message': body['output'][-1]['status']='incomplete'
        return httpx.Response(200,json=body)
    ai=offline_client(monkeypatch,handler);monkeypatch.setattr(pipeline,'AIClient',lambda _:ai)
    try: rec=pipeline.run_cycle()
    finally: ai.client.close()
    assert rec.survivors==0
    assert rec.ok==(variant not in ('exception','timeout'))
    assert rec.cost_uncertain==(variant in ('exception','timeout','usage_missing','usage_bad'))
    if variant in ('refusal','partial_message'):
        assert rec.outcome=='DEGRADED_SUCCESS' and len(rec.usages)==1 and rec.normalized_candidates==0
    assert 'secret' not in rec.model_dump_json() and 'sensitive' not in rec.model_dump_json()


def test_usage_reasoning_cached_and_write_accounting(monkeypatch):
    ai=offline_client(monkeypatch,lambda req:None)
    try:
        usage=ai._estimate('gpt-5.6-luna',{'input_tokens':1000,'output_tokens':200,
            'input_tokens_details':{'cached_tokens':100,'cache_write_tokens':100},
            'output_tokens_details':{'reasoning_tokens':150}},2)
        assert usage.estimated_cost_usd==pytest.approx(.020427)
        assert usage.reasoning_tokens==150 and usage.output_tokens==200
    finally: ai.client.close()


def test_sources_ignore_annotations_model_text_and_nested_impostors():
    payload={'output':[{'type':'message','content':[{'type':'output_text','text':'https://fake.example',
        'annotations':[{'type':'url_citation','url':'https://cited.example'}]}]},
        {'type':'web_search_call','status':'failed','action':{'sources':[{'url':'https://failed.example'}]}},
        {'type':'web_search_call','status':'completed','action':{'sources':[{'url':'https://real.example/doc?id=1'}]}}],
        'impostor':{'type':'web_search_call','status':'completed','action':{'sources':[{'url':'https://impostor.example'}]}}}
    assert _collect_urls(payload)=={'https://real.example/doc?id=1'}
