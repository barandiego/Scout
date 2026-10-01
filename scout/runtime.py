from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from .models import Usage


def _parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


@dataclass
class AIResult:
    data: Any
    usage: Usage


class AIClient:
    """Replaceable AI runtime boundary. Core/domain code calls only this class."""

    def __init__(self, pricing: dict[str, Any]):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI SDK is required for live Scout runs.") from exc
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=key)
        self.pricing = pricing

    def _estimate(self, model: str, usage_obj: Any, web_calls: int) -> Usage:
        inp = int(getattr(usage_obj, "input_tokens", 0) or 0)
        out = int(getattr(usage_obj, "output_tokens", 0) or 0)
        cached = 0
        details = getattr(usage_obj, "input_tokens_details", None)
        if details is not None:
            cached = int(getattr(details, "cached_tokens", 0) or 0)
        rate = self.pricing.get("models", {}).get(model, {})
        uncached = max(0, inp - cached)
        cost = (
            uncached * float(rate.get("input_per_million", 0)) / 1_000_000
            + cached * float(rate.get("cached_input_per_million", 0)) / 1_000_000
            + out * float(rate.get("output_per_million", 0)) / 1_000_000
            + web_calls * float(self.pricing.get("web_search_per_call", 0))
        )
        return Usage(
            model=model,
            input_tokens=inp,
            cached_tokens=cached,
            output_tokens=out,
            web_search_calls=web_calls,
            estimated_cost_usd=round(cost, 6),
        )

    def json_research(
        self,
        *,
        model: str,
        instructions: str,
        prompt: str,
        max_output_tokens: int,
        web_search: bool,
        max_tool_calls: int = 0,
        reasoning_effort: str = "low",
    ) -> AIResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
            "reasoning": {"effort": reasoning_effort},
        }
        if web_search:
            kwargs.update({
                "tools": [{"type": "web_search", "search_context_size": "low"}],
                "tool_choice": "required",
                "max_tool_calls": max_tool_calls,
            })
        response = self.client.responses.create(**kwargs)
        web_calls = sum(
            1 for item in response.output
            if getattr(item, "type", "") == "web_search_call"
        )
        return AIResult(
            data=_parse_json(response.output_text),
            usage=self._estimate(model, response.usage, web_calls),
        )
