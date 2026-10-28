"""Provisional bounded recovery; never advances or certifies a source cursor."""
from __future__ import annotations
import hashlib
from datetime import datetime, timedelta, timezone
from .procurement_core import ProcurementDataError

def _time(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ProcurementDataError("invalid_recovery_time") from None
    if dt.tzinfo is None or dt.microsecond:
        raise ProcurementDataError("recovery_time_requires_whole_second_timezone")
    return dt.astimezone(timezone.utc)

def _iso(value):
    return value.isoformat().replace("+00:00", "Z")

def _key(start, end):
    return hashlib.sha256((start + "|" + end).encode()).hexdigest()

def next_window(store, start, end):
    """Replay a fixed range's durable split tree, oldest interval first."""
    lo, hi = _time(start), _time(end)
    if hi <= lo or hi - lo > timedelta(days=366):
        raise ProcurementDataError("invalid_recovery_range")
    plan = _key(_iso(lo), _iso(hi))
    known = {}
    for event in store.events:
        if event.get("kind") != "recovery_window" or event.get("plan") != plan:
            continue
        a, b, action = event.get("start"), event.get("end"), event.get("action")
        if not isinstance(a, str) or not isinstance(b, str) or action not in ("split", "observed"):
            raise ProcurementDataError("invalid_recovery_state")
        if event != {"event_id": "recovery:" + plan + ":" + _key(a, b), "kind": "recovery_window", "plan": plan, "start": a, "end": b, "action": action}:
            raise ProcurementDataError("invalid_recovery_state")
        known[(a, b)] = action
    pending = [(lo, hi)]
    visited = 0
    while pending:
        a, b = pending.pop()
        visited += 1
        if visited > 10000:
            raise ProcurementDataError("recovery_tree_too_large")
        sa, sb = _iso(a), _iso(b)
        action = known.get((sa, sb))
        if not action:
            return plan, sa, sb
        if action == "split":
            seconds = int((b - a).total_seconds())
            if seconds < 2:
                raise ProcurementDataError("invalid_recovery_split")
            mid = a + timedelta(seconds=seconds // 2)
            # Shared endpoints overlap; this is not proof of source completeness.
            pending.extend([(mid, b), (a, mid)])
    return plan, None, None

def record_window(store, plan, start, end, action):
    if action not in ("observed", "split"):
        raise ProcurementDataError("invalid_recovery_action")
    event = {"event_id": "recovery:" + plan + ":" + _key(start, end),
             "kind": "recovery_window", "plan": plan, "start": start,
             "end": end, "action": action}
    store._append(event)