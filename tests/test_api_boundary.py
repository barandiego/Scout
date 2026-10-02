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

SOURCES = ['https://primary.example/a', 'https://independent.example/b']
CRITIC = {'fatal': False, 'critic_case': 'No fatal contradiction found.',
          'contrary_evidence': [], 'unknowns': [], 'falsification_conditions': [],
          'evidence_confidence': .75}
JUDGE = {'status': 'survived', 'vertical_fatal': False,
         'decision_reason': 'Evidence supports HQ review.', 'judgment_confidence': .7,
         'major_risks': [], 'unknowns': []}

def response_body(request, text, *, status='completed', sources=SOURCES):
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
        assert 'max_tool_calls' not in req
        assert 'include' not in req

def test_full_cycle_through_real_sdk(tmp_path, monkeypatch):
    isolated_cycle(tmp_path, monkeypatch)
    requests = []
    def handler(request):
        req = json.loads(request.content)
        requests.append(req)
        assert request.url.path == '/v1/responses'
        assert_contract(req)
        if 'Scout Discovery' in req['instructions']:
            data = {'candidates': [copy.deepcopy(DISCOVERY)]}
            assert req['max_output_tokens'] == 2600
        elif 'adversarial' in req['instructions']:
            data = CRITIC
            assert req['max_output_tokens'] == 1800
        else:
            data = JUDGE
            assert req['model'] == 'gpt-5.6-terra'
        return httpx.Response(200, json=response_body(req, json.dumps(data)))
    ai = offline_client(monkeypatch, handler)
    monkeypatch.setattr(pipeline, 'AIClient', lambda pricing: ai)
    try:
        rec = pipeline.run_cycle()
    finally:
        ai.client.close()
    assert rec.ok and rec.survivors == 1
    assert rec.critic_reviews == rec.judge_reviews == 1
    assert len(requests) == 3
    assert rec.cost_usd == pytest.approx(.020916)
    assert pipeline.daily_cost_so_far() == rec.cost_usd
    assert pipeline.read_jsonl(tmp_path/'state'/'survivors.jsonl')[0]['status'] == 'survived'
    assert 'Test industrial opportunity' in (tmp_path/'reports'/'latest.md').read_text()

@pytest.mark.parametrize('text,status,sources', [
    ('{"candidates":', 'completed', SOURCES),
    ('{"candidates":[]}', 'incomplete', SOURCES),
    ('', 'completed', SOURCES),
    ('[]', 'completed', SOURCES),
    ('{"candidates":[]}', 'completed', []),
])
def test_failed_response_retains_usage(tmp_path, monkeypatch, text, status, sources):
    isolated_cycle(tmp_path, monkeypatch)
    calls = []
    def handler(request):
        req = json.loads(request.content); calls.append(req)
        assert_contract(req)
        return httpx.Response(200, json=response_body(req, text, status=status, sources=sources))
    ai = offline_client(monkeypatch, handler)
    monkeypatch.setattr(pipeline, 'AIClient', lambda pricing: ai)
    try:
        rec = pipeline.run_cycle()
    finally:
        ai.client.close()
    assert not rec.ok and rec.errors == 1 and rec.survivors == 0
    assert len(calls) == 1  # No paid JSON-repair call.
    assert rec.cost_usd == pytest.approx(.010076)
    assert pipeline.daily_cost_so_far() == rec.cost_usd
    assert pipeline.read_jsonl(tmp_path/'state'/'runs.jsonl')[-1]['cost_usd'] == rec.cost_usd
    assert 'discovery_error:AIResponseError' in (tmp_path/'reports'/'latest.md').read_text()

@pytest.mark.parametrize('stage,bad', [
    ('discovery', {}),
    ('discovery', {'candidates': [None]}),
    ('discovery', {'candidates': [{**DISCOVERY, 'major_risks': None}]}),
    ('critic', {}),
    ('critic', {**CRITIC, 'fatal': 'true'}),
    ('critic', {**CRITIC, 'unknowns': None}),
    ('critic', {**CRITIC, 'evidence_confidence': 1.2}),
    ('judge', {}),
    ('judge', {**JUDGE, 'vertical_fatal': 'true'}),
    ('judge', {**JUDGE, 'unknowns': 'none'}),
    ('judge', {**JUDGE, 'judgment_confidence': -1}),
    ('judge', {**JUDGE, 'status': 'candidate'}),
    ('judge', {**JUDGE, 'judgment_confidence': float('nan')}),
])
def test_invalid_decisions_fail_closed_and_are_metered(tmp_path, monkeypatch, stage, bad):
    isolated_cycle(tmp_path, monkeypatch)
    calls = []
    def handler(request):
        req = json.loads(request.content); calls.append(req); assert_contract(req)
        current = ('discovery' if 'Scout Discovery' in req['instructions'] else
                   'critic' if 'adversarial' in req['instructions'] else 'judge')
        data = bad if current == stage else {
            'discovery': {'candidates': [DISCOVERY]}, 'critic': CRITIC, 'judge': JUDGE}[current]
        return httpx.Response(200, json=response_body(req, json.dumps(data)))
    ai = offline_client(monkeypatch, handler)
    monkeypatch.setattr(pipeline, 'AIClient', lambda pricing: ai)
    try:
        rec = pipeline.run_cycle()
    finally:
        ai.client.close()
    assert not rec.ok and rec.errors == 1 and rec.survivors == 0
    assert len(calls) == {'discovery': 1, 'critic': 2, 'judge': 3}[stage]
    assert rec.cost_usd == pytest.approx(
        {'discovery': .010076, 'critic': .020152, 'judge': .020916}[stage])
    if stage != 'discovery':
        assert rec.watches == 1
        assert pipeline.read_jsonl(tmp_path/'state'/'watch.jsonl')[0]['decision_reason'] == stage+'_error'

@pytest.mark.parametrize('decision', [
    {**CRITIC, 'fatal': True}, {**CRITIC, 'evidence_confidence': .4}])
def test_critic_failure_of_fatal_gate_prevents_judgment(tmp_path, monkeypatch, decision):
    isolated_cycle(tmp_path, monkeypatch)
    calls = []
    def handler(request):
        req = json.loads(request.content); calls.append(req)
        data = {'candidates': [DISCOVERY]} if len(calls) == 1 else decision
        return httpx.Response(200, json=response_body(req, json.dumps(data)))
    ai = offline_client(monkeypatch, handler)
    monkeypatch.setattr(pipeline, 'AIClient', lambda pricing: ai)
    try:
        rec = pipeline.run_cycle()
    finally:
        ai.client.close()
    assert rec.ok and rec.rejected == 1 and rec.survivors == 0
    assert rec.judge_reviews == 0 and len(calls) == 2

def test_budget_deferral_does_not_send_another_request(tmp_path, monkeypatch):
    isolated_cycle(tmp_path, monkeypatch)
    cfg_path = tmp_path/'config'/'scout.yaml'
    cfg = pipeline.load_yaml(cfg_path)
    cfg['budget']['cycle_usd'] = .03
    import yaml
    cfg_path.write_text(yaml.safe_dump(cfg))
    calls = []
    def handler(request):
        req = json.loads(request.content); calls.append(req)
        return httpx.Response(200, json=response_body(req, json.dumps({'candidates': [DISCOVERY]})))
    ai = offline_client(monkeypatch, handler)
    monkeypatch.setattr(pipeline, 'AIClient', lambda pricing: ai)
    try:
        rec = pipeline.run_cycle()
    finally:
        ai.client.close()
    assert rec.ok and rec.watches == 1 and len(calls) == 1
    assert rec.critic_reviews == rec.judge_reviews == 0

def test_url_grounding_uses_search_sources_and_keeps_query():
    dumped = {'url': 'https://fabricated.example', 'output': [
        {'type': 'message', 'content': [{'text': '{"url":"https://fake.example"}'}]},
        {'type': 'web_search_call', 'status': 'failed',
         'action': {'sources': [{'url': 'https://failed.example'}]}},
        {'type': 'web_search_call', 'status': 'completed',
         'action': {'sources': [{'url': 'https://real.example/doc?id=1'}]}}]}
    urls = _collect_urls(dumped)
    assert urls == {'https://real.example/doc?id=1'}
    raw = {'evidence': [{'url': 'https://real.example/doc?id=2'},
                        {'url': 'https://real.example/doc?id=1'}]}
    assert pipeline._ground_raw(raw, urls)['evidence'] == [raw['evidence'][1]]

@pytest.mark.parametrize('text', ['prose {"a":1}', '{"a":1} trailing', '[]', 'null'])
def test_parser_rejects_ambiguous_or_nonobject_output(text):
    with pytest.raises(ValueError):
        _parse_json(text)
