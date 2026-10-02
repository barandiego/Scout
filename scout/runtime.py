"""Responses adapter. Provider output remains data; accounting precedes interpretation."""
from __future__ import annotations
import os
import math
from dataclasses import dataclass, field
from typing import Any
from .models import Usage
from .boundary import parse_object, url_key, BoundaryError

_parse_json = parse_object


def _collect_urls(obj: Any) -> set[str]:
    # Inspect only the documented top-level tool envelope. An annotation is a
    # citation, not the complete search source set; model text cannot add provenance.
    output = obj.get('output', []) if isinstance(obj, dict) else []
    urls = set()
    for item in output if isinstance(output, list) else []:
        if not isinstance(item, dict) or item.get('type') != 'web_search_call' or item.get('status') != 'completed':
            continue
        action = item.get('action')
        sources = action.get('sources') if isinstance(action, dict) else []
        for source in sources if isinstance(sources, list) else []:
            if isinstance(source, dict) and url_key(source.get('url')):
                urls.add(source['url'])
    return urls


@dataclass
class AIResult:
    data: Any
    usage: Usage
    source_urls: set[str]
    diagnostic: dict = field(default_factory=lambda: {'response_status': 'completed'})


class AIResponseError(RuntimeError):
    def __init__(self, code: str, usage: Usage, *, infrastructure: bool = False, diagnostic: dict | None = None):
        super().__init__(code)
        self.usage = usage
        self.infrastructure = infrastructure
        self.diagnostic = diagnostic or {'reason': code}


class AIClient:
    def __init__(self, pricing: dict[str, Any]):
        from openai import OpenAI
        key = os.environ.get('OPENAI_API_KEY')
        if not key:
            raise RuntimeError('missing_api_key')
        self.client = OpenAI(api_key=key, max_retries=0, timeout=60.0)
        self.pricing = pricing

    def validate_models(self, models: list[str]) -> None:
        available = {m.id for m in self.client.models.list().data}
        if set(models) - available:
            raise RuntimeError('configured_model_unavailable')

    def _estimate(self, model: str, usage_obj: Any, web_calls: int) -> Usage:
        if hasattr(usage_obj, 'model_dump'):
            usage_obj = usage_obj.model_dump()
        obj = usage_obj if isinstance(usage_obj, dict) else {}
        notes = []
        def count(value, name):
            if type(value) is int and 0 <= value <= 10**12:
                return value
            notes.append('missing_or_invalid_' + name)
            return 0
        inp = count(obj.get('input_tokens'), 'input_tokens')
        out = count(obj.get('output_tokens'), 'output_tokens')
        details = obj.get('input_tokens_details')
        details = details if isinstance(details, dict) else {}
        cached = count(details.get('cached_tokens', 0), 'cached_tokens')
        writes = count(details.get('cache_write_tokens') or 0, 'cache_write_tokens')
        if cached + writes > inp:
            notes.append('inconsistent_cache_counts')
            cached = writes = 0  # conservative: bill all input as uncached
        output_details = obj.get('output_tokens_details')
        reasoning = count(output_details.get('reasoning_tokens', 0), 'reasoning_tokens') if isinstance(output_details, dict) else 0
        rate = self.pricing['models'][model]
        long = inp > 272_000
        input_factor, output_factor = (2, 1.5) if long else (1, 1)
        cost = ((inp-cached-writes)*rate['input_per_million'] + cached*rate['cached_input_per_million']
                + writes*rate['input_per_million']*1.25)*input_factor/1_000_000
        # Reasoning is INCLUDED in output_tokens; never count it twice.
        cost += out*rate['output_per_million']*output_factor/1_000_000
        cost += web_calls*self.pricing['web_search_per_call']
        return Usage(model=model, input_tokens=inp, cached_tokens=cached, output_tokens=out,
                     reasoning_tokens=reasoning, cache_write_tokens=writes, web_search_calls=web_calls,
                     estimated_cost_usd=round(cost, 9), available=bool(obj) and not notes,
                     accounting_notes=notes)

    def json_research(self, *, model: str, instructions: str, prompt: str,
                      max_output_tokens: int, web_search: bool, max_tool_calls: int = 0,
                      reasoning_effort: str = 'low') -> AIResult:
        rate = self.pricing.get('models', {}).get(model)
        if not rate or any(type(rate.get(k)) not in (int, float) or not math.isfinite(rate[k]) or rate[k] < 0
                           for k in ('input_per_million', 'cached_input_per_million', 'output_per_million')):
            raise ValueError('invalid_model_pricing')
        if max_output_tokens <= 0 or (web_search and max_tool_calls <= 0):
            raise ValueError('invalid_request_caps')
        kwargs = dict(model=model, instructions=instructions, input=prompt,
                      max_output_tokens=max_output_tokens, reasoning={'effort': reasoning_effort}, store=False)
        if web_search:
            kwargs['instructions'] += '\nReturn exactly one JSON object. Put source URLs inside JSON strings.'
            kwargs.update(tools=[{'type': 'web_search', 'search_context_size': 'low'}],
                          tool_choice='required', include=['web_search_call.action.sources'], max_tool_calls=max_tool_calls)
        else:
            kwargs['text'] = {'format': {'type': 'json_object'}}
        try:
            response = self.client.responses.create(**kwargs)
        except Exception as exc:
            # No exception text: it may include prompts, credentials, or provider body.
            # No retry; transport exceptions can represent a billed but lost response.
            body = getattr(exc, 'body', None)
            returned_usage = getattr(exc, 'usage', None) or (body.get('usage') if isinstance(body, dict) else None)
            usage = self._estimate(model, returned_usage, 0)
            usage.available = False  # tool accounting / completion unknown after transport error
            raise AIResponseError('api_exception', usage, infrastructure=True,
                                  diagnostic={'response_status': 'exception', 'exception_type': type(exc).__name__}) from None
        dumped = response if isinstance(response, dict) else response.model_dump(warnings=False)
        output = dumped.get('output')
        output = output if isinstance(output, list) else []
        web_calls = sum(isinstance(i, dict) and i.get('type') == 'web_search_call' for i in output)
        usage = self._estimate(model, dumped.get('usage'), web_calls)
        status = dumped.get('status')
        details = dumped.get('incomplete_details')
        reason = details.get('reason') if isinstance(details, dict) else None
        # Whitelist reason codes; never persist arbitrary provider strings.
        reason = reason if reason in ('max_output_tokens', 'content_filter') else 'other' if reason else ''
        sources = _collect_urls(dumped) if web_search else set()
        diagnostic = {'response_status': status if status in ('completed', 'incomplete', 'failed', 'cancelled', 'queued', 'in_progress') else 'unknown',
                      'incomplete_reason': reason, 'grounded_source_count': len(sources),
                      'search_source_urls': sorted(url_key(u) for u in sources)[:100]}
        if status != 'completed':
            raise AIResponseError('response_not_completed', usage,
                                  infrastructure=status != 'incomplete', diagnostic=diagnostic)
        # Match SDK output_text aggregation without assuming a message's position.
        parts = [c.get('text') for i in output if isinstance(i, dict) and i.get('type') == 'message'
                 for c in (i.get('content') if isinstance(i.get('content'), list) else [])
                 if isinstance(c, dict) and c.get('type') == 'output_text' and isinstance(c.get('text'), str)]
        try:
            data = parse_object(''.join(parts))
        except BoundaryError as exc:
            raise AIResponseError(str(exc), usage, diagnostic={**diagnostic, 'reason': str(exc)}) from None
        # Zero sources is a valid research result. Grounding gates decide candidates;
        # a critic without sources is deferred by the pipeline, never a survivor.
        return AIResult(data, usage, sources, diagnostic)
