from scout.runtime import _collect_urls,_parse_json

def test_parse_json_plain_and_fenced():
    assert _parse_json('{"a":1}')=={'a':1}
    assert _parse_json('```json\n{"a":1}\n```')=={'a':1}
def test_collect_urls_recursively():
    obj={'output':[{'type':'web_search_call','action':{'sources':[{'url':'https://a.example/x'},{'url':'https://b.example/y'}]}}]}
    assert _collect_urls(obj)=={'https://a.example/x','https://b.example/y'}
