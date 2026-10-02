from __future__ import annotations
import json, os
from dataclasses import dataclass
from typing import Any
from .models import Usage

def _parse_json(text: str) -> Any:
    text = (text or '').strip()
    if not text:
        raise ValueError('empty model output')
    if text.startswith('```'):
        lines=text.splitlines()[1:]
        if lines and lines[-1].strip()=='```': lines=lines[:-1]
        text='\n'.join(lines).strip()
    data=json.loads(text)
    if not isinstance(data,dict): raise ValueError('model output must be a JSON object')
    return data

def _collect_urls(obj: Any) -> set[str]:
    # Ground only to tool-returned sources, never arbitrary model-authored URLs.
    urls:set[str]=set()
    if isinstance(obj,dict):
        if obj.get('type')=='web_search_call' and obj.get('status')=='completed':
            for source in obj.get('action',{}).get('sources',[]) or []:
                url=source.get('url') if isinstance(source,dict) else None
                if isinstance(url,str) and url.startswith(('http://','https://')): urls.add(url)
        else:
            for v in obj.values(): urls.update(_collect_urls(v))
    elif isinstance(obj,(list,tuple)):
        for v in obj: urls.update(_collect_urls(v))
    return urls

@dataclass
class AIResult:
    data: Any
    usage: Usage
    source_urls: set[str]

class AIResponseError(RuntimeError):
    def __init__(self,message:str,usage:Usage):
        super().__init__(message); self.usage=usage

class AIClient:
    def __init__(self, pricing: dict[str,Any]):
        from openai import OpenAI
        key=os.environ.get('OPENAI_API_KEY')
        if not key: raise RuntimeError('OPENAI_API_KEY is not set')
        self.client=OpenAI(api_key=key,max_retries=0,timeout=60.0); self.pricing=pricing

    def validate_models(self, models:list[str]) -> None:
        available={m.id for m in self.client.models.list().data}
        missing=sorted(set(models)-available)
        if missing: raise RuntimeError(f'Configured OpenAI model(s) unavailable: {missing}')

    def _estimate(self, model:str, usage_obj:Any, web_calls:int)->Usage:
        inp=int(getattr(usage_obj,'input_tokens',0) or 0); out=int(getattr(usage_obj,'output_tokens',0) or 0)
        details=getattr(usage_obj,'input_tokens_details',None); cached=int(getattr(details,'cached_tokens',0) or 0) if details else 0
        rate=self.pricing.get('models',{}).get(model)
        if not rate: raise RuntimeError(f'Missing pricing for configured model: {model}')
        cost=((inp-cached)*float(rate['input_per_million'])+cached*float(rate['cached_input_per_million'])+out*float(rate['output_per_million']))/1_000_000
        cost+=web_calls*float(self.pricing.get('web_search_per_call',0))
        return Usage(model=model,input_tokens=inp,cached_tokens=cached,output_tokens=out,web_search_calls=web_calls,estimated_cost_usd=round(cost,6))

    def json_research(self,*,model:str,instructions:str,prompt:str,max_output_tokens:int,web_search:bool,max_tool_calls:int=0,reasoning_effort:str='low')->AIResult:
        if model not in self.pricing.get('models',{}): raise ValueError(f'Missing pricing for configured model: {model}')
        if max_output_tokens<=0 or (web_search and max_tool_calls<=0): raise ValueError('Research requires positive output and search caps')
        kwargs:dict[str,Any]={
            'model':model,'instructions':instructions,'input':prompt,
            'max_output_tokens':max_output_tokens,'reasoning':{'effort':reasoning_effort},
            'store':False,
        }
        if web_search:
            # Web search rejects JSON mode. Parse prompted JSON locally and fail
            # closed without a second paid repair call.
            kwargs['instructions']+='\nReturn exactly one JSON object, with no prose, Markdown, or citation markers outside it. Put source URLs inside JSON strings.'
            kwargs.update({'tools':[{'type':'web_search','search_context_size':'low'}],'tool_choice':'required','include':['web_search_call.action.sources']})
            kwargs['max_tool_calls']=max_tool_calls
        else:
            kwargs['text']={'format':{'type':'json_object'}}
        response=self.client.responses.create(**kwargs)
        dumped=response.model_dump() if hasattr(response,'model_dump') else {}
        source_urls=_collect_urls(dumped) if web_search else set()
        web_calls=sum(1 for item in getattr(response,'output',[]) if getattr(item,'type','')=='web_search_call')
        usage=self._estimate(model,getattr(response,'usage',None),web_calls)
        try:
            if getattr(response,'status',None)!='completed': raise ValueError(f'OpenAI response status={getattr(response,"status",None)}')
            data=_parse_json(getattr(response,'output_text',''))
            if web_search and not source_urls: raise ValueError('web research returned no completed search sources')
        except (ValueError,TypeError) as exc:
            raise AIResponseError(str(exc),usage) from exc
        return AIResult(data=data,usage=usage,source_urls=source_urls)
