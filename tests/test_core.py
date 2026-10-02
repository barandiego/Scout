import copy
import math
import random
import pytest
from pydantic import ValidationError
from scout.boundary import confidence, boolean, strings, RawDiscoverySignal, url_key, parse_object, BoundaryError
from scout.pipeline import normalize_candidate, hard_gate_reasons, is_duplicate, similarity, Budget
from scout.models import Opportunity, Usage
from test_integration import candidate, SOURCES


@pytest.mark.parametrize('value,expected', [(0.8,.8), ('0.8',.8), ('80%',.8), (80,None), ('high',None),
    ('medium',None), (None,None), ([],None), ({'score':.8},None), ('NaN',None), ('Infinity',None),
    (float('nan'),None), (float('inf'),None), (-.1,None), (1.2,None), (8,None), (True,None), (' 82% ',.82)])
def test_confidence_policy(value, expected):
    assert confidence(value) == expected
    op = normalize_candidate(candidate(evidence_confidence=value), SOURCES)
    assert math.isfinite(op.evidence_confidence)
    if expected is None:
        assert 'low_evidence_confidence' in hard_gate_reasons(op)


@pytest.mark.parametrize('value,expected', [(True,True),(False,False),('true',True),('false',False),('yes',True),
    ('no',False),(1,True),(0,False),(None,None),('nonsense',None),([],None),({},None),(' FALSE ',False)])
def test_boolean_policy(value, expected):
    assert boolean(value) is expected
    op = normalize_candidate(candidate(real=value), SOURCES)
    assert op.real is (expected is True)


@pytest.mark.parametrize('value,expected', [('risk',['risk']),(None,[]),(['a',None,1,{},'a','b'],['a','b']), ({},[])])
def test_lists(value, expected):
    assert strings(value) == expected


@pytest.mark.parametrize('field', ['name','thesis','signal','participation_path','evidence','evidence_confidence','real','actionable'])
def test_missing_fields(field):
    r = candidate(); r.pop(field)
    op, d = RawDiscoverySignal(r, SOURCES).canonicalize({'general'})
    assert op is None or hard_gate_reasons(op)


def test_missing_optional_fields_is_fine():
    assert not hard_gate_reasons(normalize_candidate(candidate(), SOURCES))


@pytest.mark.parametrize('sources,expected', [(SOURCES,2), ({next(iter(SOURCES))},1), (set(),0), ({'https://fabricated.example'},0)])
def test_grounding_counts_only_returned(sources, expected):
    op=normalize_candidate(candidate(), sources)
    assert len(op.evidence)==expected
    assert bool(hard_gate_reasons(op)) is (expected<2)


@pytest.mark.parametrize('url', ['javascript:alert(1)','file:///a','https://','https://bad host/a','https://user:pass@host.example',
    'https://host.example:bad/a','https://[invalid/a',[],{},None])
def test_bad_url(url):
    assert url_key(url)==''
    r=candidate();r['evidence'][0]['url']=url
    assert len(normalize_candidate(r,SOURCES).evidence)==1


def test_urls_tracking_query_and_scheme():
    assert url_key('https://EXAMPLE.com/doc?id=1&utm_source=x#top')=='https://example.com/doc?id=1'
    assert url_key('http://example.com/doc') != url_key('https://example.com/doc')
    assert url_key('https://example.com/doc?id=1') != url_key('https://example.com/doc?id=2')
    r=candidate(); r['evidence'].append(copy.deepcopy(r['evidence'][0]))
    assert len(normalize_candidate(r,SOURCES).evidence)==2


def test_material_update_requires_new_grounded_evidence():
    a=normalize_candidate(candidate(),SOURCES)
    r=candidate(material_update=True,update_summary='New financing condition materially changes investment economics')
    r['evidence'].append({'title':'new','url':'https://new.example/doc','source_type':'primary','claim':'new condition'})
    fake=normalize_candidate(r,SOURCES)
    assert is_duplicate(fake,[a],.72)
    real=normalize_candidate(r,SOURCES|{'https://new.example/doc'})
    assert not is_duplicate(real,[a],.72) and real.opportunity_id==a.opportunity_id


def test_exact_overlap_and_distinct_thesis():
    a=normalize_candidate(candidate(),SOURCES)
    b=normalize_candidate(candidate(),SOURCES)
    assert similarity(a,b)==1 and is_duplicate(b,[a],.72)
    b=normalize_candidate(candidate(name=a.name,thesis='Currency hedging contracts provide export financing spreads'),SOURCES)
    assert not is_duplicate(b,[a,{},None],.72) and b.opportunity_id != a.opportunity_id
    b=normalize_candidate(candidate(thesis=a.thesis+' significantly'),SOURCES)
    assert is_duplicate(b,[a],.72)


@pytest.mark.parametrize('raw', [None,[],1,'bad',{'name':' '},{'name':{},'thesis':[]}, {'name':'a'}])
def test_no_canonical_record_for_missing_identity(raw):
    op,d=RawDiscoverySignal(raw,SOURCES).canonicalize({'general'})
    assert op is None and d.outcome=='quarantined'


def test_canonical_strict_validation():
    good=normalize_candidate(candidate(),SOURCES).model_dump()
    for changes in ({'real':'true'}, {'evidence_confidence':float('nan')}, {'name':''}, {'unexpected':'field'}, {'primary_sources':[]}):
        with pytest.raises(ValidationError):
            Opportunity.model_validate({**good,**changes})


def test_huge_unicode_nested_and_whitespace():
    op=normalize_candidate(candidate(name='  Economía 🇨🇱 '+ 'x'*10000, signal='\ud800 hello',
                                     major_risks=[{'nested': {'bad':[]}}, '日本語', '🙂', '   ']), SOURCES)
    assert len(op.name)<=2000 and op.major_risks==['日本語','🙂']
    op.model_dump_json()


def test_seeded_external_value_fuzz():
    rng=random.Random(206)
    values=[None,True,False,0,1,-1,80,1e100,float('nan'),'high','80%',' ',[],{},['a',None],{'score':.8}]
    fields=list(candidate())+['unknowns','material_update','status','opportunity_id']
    for _ in range(1000):
        r=candidate()
        for k in rng.sample(fields, rng.randint(1,6)):
            r[k]=rng.choice(values)
        op,d=RawDiscoverySignal(r,SOURCES).canonicalize({'general'})
        if op:
            Opportunity.model_validate(op.model_dump())
            hard_gate_reasons(op)
        else:
            assert d.reasons


@pytest.mark.parametrize('s', ['{"a":1}', '```json\n{"a":1}\n```', 'Here is JSON: {"a":1}', '{"a":1} Done.'])
def test_tolerant_single_object(s):
    assert parse_object(s)=={'a':1}


@pytest.mark.parametrize('s', ['', '[]','null','{"a":','{"a":1} {"b":2}', '[{"a":1}]', '{"a":1,"a":2}', '{"broken": {"a":1}', '{"a":1} trailing {'])
def test_ambiguous_or_truncated_json_rejected(s):
    with pytest.raises(BoundaryError): parse_object(s)


def test_one_bad_evidence_item_keeps_two_good_sources():
    raw=candidate();raw['evidence']=[None, {'url':'javascript:bad'}, *raw['evidence']]
    op=normalize_candidate(raw,SOURCES)
    assert not hard_gate_reasons(op) and len(op.evidence)==2


def test_tracking_variants_ground_and_deduplicate():
    raw=candidate();raw['evidence'][0]['url']+='?utm_source=ad'
    raw['evidence'].append({**raw['evidence'][0],'url':'https://primary.example/a?utm_campaign=b'})
    op=normalize_candidate(raw,SOURCES)
    assert len(op.evidence)==2 and not hard_gate_reasons(op)


def test_singleton_evidence_object_is_safe_but_fails_two_source_gate():
    raw=candidate();raw['evidence']=raw['evidence'][0]
    op=normalize_candidate(raw,SOURCES)
    assert len(op.evidence)==1 and hard_gate_reasons(op)
