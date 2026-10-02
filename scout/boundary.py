"""The only conversion from probabilistic content to canonical Scout records.

Policies are deliberately conservative. Unknown never means true/high confidence.
No repair requests, eval, recursive URL discovery, or model-controlled state fields.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .models import Opportunity, EvidenceItem, CriticDecision, JudgeDecision

MAX_TEXT = 2000
MAX_ITEMS = 20

class BoundaryError(ValueError):
    """A sanitized reason code, never provider text or Pydantic input repr."""


def text(value: Any, limit: int = MAX_TEXT) -> str:
    return value.encode('utf-8', errors='replace').decode('utf-8').strip()[:limit] if isinstance(value, str) else ''


def confidence(value: Any) -> float | None:
    # Bare numbers must be probabilities. Only explicit % permits percentage scale.
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        percent = isinstance(value, str) and value.strip().endswith('%')
        number = float(value.strip()[:-1] if percent else value)
        if percent:
            number /= 100
        return number if math.isfinite(number) and 0 <= number <= 1 else None
    except (ValueError, TypeError, OverflowError):
        return None


def boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if type(value) in (int, float) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        return {'true': True, 'yes': True, '1': True,
                'false': False, 'no': False, '0': False}.get(value.strip().lower())
    return None


def strings(value: Any) -> list[str]:
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return list(dict.fromkeys(s for x in values[:MAX_ITEMS] if (s := text(x))))


def url_key(value: Any) -> str:
    value = text(value, 4097)
    if not value or len(value) > 4096 or re.search(r'[\s\x00-\x1f\\]', value):
        return ''
    try:
        p = urlsplit(value)
        if p.scheme.lower() not in ('http', 'https') or not p.hostname or p.username or p.password:
            return ''
        host = p.hostname.encode('idna').decode('ascii').lower()
        if '.' not in host or not re.fullmatch(r'[a-z0-9.-]+', host):
            return ''
        port = p.port
        if port and port != {'http': 80, 'https': 443}[p.scheme.lower()]:
            host += ':' + str(port)
        # Keep scheme, www, path and substantive query parameters; no invented redirects.
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith('utm_') and k.lower() not in ('gclid', 'fbclid')]
        return urlunsplit((p.scheme.lower(), host, p.path or '/', urlencode(query), ''))
    except (ValueError, UnicodeError):
        return ''


def parse_object(value: Any) -> dict:
    if not isinstance(value, str) or not value.strip() or len(value) > 250_000:
        raise BoundaryError('empty_or_oversize_output')
    s = value.strip()
    start = s.find('{')
    if start < 0 or any(c in s[:start] for c in '[{'):
        raise BoundaryError('no_object')
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise BoundaryError('duplicate_json_key')
            result[k] = v
        return result
    decoder = json.JSONDecoder(object_pairs_hook=pairs)
    try:
        data, end = decoder.raw_decode(s, start)
    except (ValueError, RecursionError):
        raise BoundaryError('invalid_json') from None
    # Recover one complete object with harmless prose/fences, never extract nested
    # objects from a broken enclosing container or choose between competing objects.
    if not isinstance(data, dict) or any(c in s[end:] for c in '{}[]'):
        raise BoundaryError('ambiguous_json')
    return data


@dataclass
class CandidateDiagnostic:
    index: int
    stage: str = 'normalization'
    outcome: str = 'quarantined'
    reasons: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    grounded_sources: int = 0
    retry_justified: bool = False


@dataclass
class RawDiscoverySignal:
    payload: Any
    source_urls: set[str]
    index: int = 0

    def canonicalize(self, verticals: set[str]) -> tuple[Opportunity | None, CandidateDiagnostic]:
        d = CandidateDiagnostic(self.index)
        r = self.payload
        if not isinstance(r, dict):
            d.reasons.append('candidate_not_object')
            return None, d
        values = {}
        aliases = {'name': 'title', 'thesis': 'economic_implication',
                   'value_capture_mechanism': 'value_capture', 'signal': 'observed_change'}
        for name in ('name', 'type', 'vertical', 'geography', 'discovery_lens', 'signal',
                     'what_changed', 'why_now', 'thesis', 'value_capture_mechanism',
                     'participation_path', 'update_summary', 'capital_required',
                     'diego_hours_initial', 'diego_hours_ongoing', 'ai_leverage', 'time_horizon'):
            raw = r.get(name, r.get(aliases.get(name, '')))
            values[name] = text(raw)
            if raw is not None and values[name] != raw:
                d.changes.append(name + ':sanitized')
        for name in ('name', 'thesis', 'signal'):
            if not values[name]:
                d.reasons.append('missing_' + name)
        if d.reasons:
            return None, d
        values['vertical'] = values['vertical'] if values['vertical'] in verticals else 'general'
        values['type'] = values['type'] or 'unknown'
        values['geography'] = values['geography'] or 'global'
        for name in ('contrary_evidence', 'major_risks', 'unknowns', 'falsification_conditions'):
            values[name] = strings(r.get(name))
            if r.get(name) != values[name]:
                d.changes.append(name + ':list_sanitized')
        for name in ('real', 'actionable', 'material_update'):
            val = boolean(r.get(name))
            values[name] = val is True
            if type(r.get(name)) is not bool:
                d.changes.append(name + (':unknown_false' if val is None else ':boolean'))
        conf = confidence(r.get('evidence_confidence'))
        values['evidence_confidence'] = conf if conf is not None else 0.0
        if type(r.get('evidence_confidence')) is not float or conf is None:
            d.changes.append('evidence_confidence:' + ('unknown_zero' if conf is None else 'probability'))
        sources = {url_key(u): u for u in self.source_urls if url_key(u)}
        evidence, seen = [], set()
        raw_evidence = r.get('evidence')
        if isinstance(raw_evidence, dict):
            raw_evidence = [raw_evidence]
            d.changes.append('evidence:singleton_list')
        for e in (raw_evidence if isinstance(raw_evidence, list) else [])[:MAX_ITEMS]:
            if not isinstance(e, dict):
                d.reasons.append('discarded_nonobject_evidence')
                continue
            key = url_key(e.get('url'))
            if not key or key not in sources:
                d.reasons.append('discarded_ungrounded_url')
                continue
            if key in seen:
                d.changes.append('evidence:duplicate_removed')
                continue
            claim = text(e.get('claim'))
            if not claim:
                d.reasons.append('discarded_missing_claim')
                continue
            seen.add(key)
            kind = text(e.get('source_type'))
            evidence.append(EvidenceItem(title=text(e.get('title')) or 'Source', url=key,
                source_type=kind if kind in ('primary', 'independent') else 'other',
                claim=claim, grounded=True, returned_url=sources[key], domain=urlsplit(key).hostname or ''))
        values['evidence'] = evidence
        values['primary_sources'] = [e.url for e in evidence if e.source_type == 'primary']
        values['independent_sources'] = [e.url for e in evidence if e.source_type == 'independent']
        now = datetime.now(timezone.utc).isoformat()
        # Identity includes thesis; one company can contain different opportunities.
        identity = '|'.join(values[k].casefold() for k in ('name', 'vertical', 'geography', 'thesis'))
        values.update(opportunity_id='opp_' + hashlib.sha256(identity.encode()).hexdigest()[:20],
                      discovered_at=now, last_updated=now)
        op = Opportunity.model_validate(values)
        d.outcome = 'accepted'
        d.grounded_sources = len(evidence)
        return op, d


def decision(raw: Any, stage: str) -> CriticDecision | JudgeDecision:
    if not isinstance(raw, dict):
        raise BoundaryError('decision_not_object')
    flag = 'fatal' if stage == 'critic' else 'vertical_fatal'
    score = 'evidence_confidence' if stage == 'critic' else 'judgment_confidence'
    reason = 'critic_case' if stage == 'critic' else 'decision_reason'
    b, c, s = boolean(raw.get(flag)), confidence(raw.get(score)), text(raw.get(reason))
    if b is None or c is None or not s:
        raise BoundaryError('invalid_required_decision_fields')
    data = {flag: b, score: c, reason: s, 'unknowns': strings(raw.get('unknowns'))}
    if stage == 'critic':
        data.update(contrary_evidence=strings(raw.get('contrary_evidence')),
                    falsification_conditions=strings(raw.get('falsification_conditions')))
        return CriticDecision.model_validate(data)
    status = text(raw.get('status')).lower()
    if status not in ('survived', 'watch', 'rejected'):
        raise BoundaryError('invalid_judge_status')
    return JudgeDecision.model_validate({**data, 'status': status, 'major_risks': strings(raw.get('major_risks'))})
