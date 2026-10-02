from __future__ import annotations
import json, os
from dataclasses import dataclass
from typing import Any
from .models import Usage

def _parse_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty model output")
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            return json.loads(text[s:e + 1])
        raise

def _collect_urls(obj: Any) -> set[str]:
    urls: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "url" and isinstance(v, str) and v.startswith(("http://", "https://")):
                urls.add(v)
            else:
                urls.update(_collect_urls(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            urls.update(_collect_urls(v))
    return urls

@dataclass
class AIResult:
    data: Any
    usage: Usage
    source_urls: set[str]

class AIClient:
    """Replaceable OpenAI runtime boundary."""

    def __init__(self, pricing: dict[str, Any]):
        from openai import OpenAI
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=key)
        self.pricing = pricing

    def validate_models(self, models: list[str]) -> None:
        available = {m.id for m in self.client.models.list().data}
        missing = sorted(set(models) - available)
        if missing:
            raise RuntimeError(f"Configured OpenAI model(s) unavailable: {missing}")

    def _estimate(self, model: str, usage_obj: Any, web_calls: int) -> Usage:
        inp = int(getattr(usage_obj, "input_tokens", 0) or 0)
        out = int(getattr(usage_obj, "output_tokens", 0) or 0)
        details = getattr(usage_obj, "input_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
        rate = self.pricing.get("models", {}).get(model)
        if not rate:
            raise RuntimeError(f"Missing pricing for configured model: {model}")
        cost = (
            (inp - cached) * float(rate["input_per_million"])
            + cached * float(rate["cached_input_per_million"])
            + out * float(rate["output_per_million"])
        ) / 1_000_000
        cost += web_calls * float(self.pricing.get("web_search_per_call", 0))
        return Usage(model=model, input_tokens=inp, cached_tokens=cached, output_tokens=out,
                     web_search_calls=web_calls, estimated_cost_usd=round(cost, 6))

    def json_research(self, *, model: str, instructions: str, prompt: str,
                      max_output_tokens: int, web_search: bool,
                      max_tool_calls: int = 0, reasoning_effort: str = "low") -> AIResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
            "reasoning": {"effort": reasoning_effort},
            "text": {"format": {"type": "json_object"}},
            "store": False,
        }
        if web_search:
            kwargs.update({
                "tools": [{"type": "web_search", "search_context_size": "low"}],
                "tool_choice": "required",
                "include": ["web_search_call.action.sources"],
            })
            if max_tool_calls > 0:
                kwargs["max_tool_calls"] = max_tool_calls
        response = self.client.responses.create(**kwargs)
        if getattr(response, "status", "completed") not in ("completed", None):
            raise RuntimeError(f"OpenAI response status={getattr(response, 'status', None)}")
        dumped = response.model_dump() if hasattr(response, "model_dump") else {}
        source_urls = _collect_urls(dumped) if web_search else set()
        web_calls = sum(1 for item in getattr(response, "output", [])
                        if getattr(item, "type", "") == "web_search_call")
        return AIResult(
            data=_parse_json(getattr(response, "output_text", "")),
            usage=self._estimate(model, response.usage, web_calls),
            source_urls=source_urls,
        )
