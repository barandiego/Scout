"""Single-writer, atomic JSONL transactions; legacy input is read, never rewritten.

One row holds a run AND its finalized records. Checkpoints replace that row.
A pre-call reservation survives process death; incomplete calls block daily spending.
"""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from .models import Opportunity, RunRecord

class StateError(RuntimeError):
    pass


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(value, dict):
                raise ValueError()
            result.append(value)
        except (ValueError, RecursionError):
            raise StateError(f'corrupt_state:{path.name}:line_{number}') from None
    return result


def atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.path = root/'state'/'transactions.jsonl'
        self.rows = read_jsonl(self.path)
        self.legacy_runs = read_jsonl(root/'state'/'runs.jsonl')
        self.legacy_ops = []
        try:
            ids = set()
            for row in self.rows:
                run = RunRecord.model_validate(row['run'])
                if run.run_id in ids:
                    raise ValueError()
                ids.add(run.run_id)
                if not isinstance(row['opportunities'], list):
                    raise ValueError()
                op_ids = set()
                for op in row['opportunities']:
                    validated = Opportunity.model_validate(op)
                    if validated.opportunity_id in op_ids:
                        raise ValueError()
                    op_ids.add(validated.opportunity_id)
                    if validated.status == 'candidate':
                        raise ValueError()
            # Legacy costs must be readable before any new paid work.
            unique = {}
            for r in self.legacy_runs:
                record = RunRecord.model_validate(r)
                if record.cost_usd < 0:
                    raise ValueError()
                prior = unique.get(record.run_id)
                if prior is not None and prior != r:
                    raise ValueError()
                unique[record.run_id] = r
            if ids & unique.keys():
                raise ValueError()
            self.legacy_runs = list(unique.values())
            for filename in ('survivors.jsonl', 'watch.jsonl', 'rejected.jsonl'):
                for op in read_jsonl(root/'state'/filename):
                    self.legacy_ops.append(Opportunity.model_validate(op))
        except (ValueError, KeyError, TypeError):
            raise StateError('invalid_state_schema') from None

    def runs(self) -> list[dict]:
        return self.legacy_runs + [r['run'] for r in self.rows]

    def opportunities(self) -> list[Opportunity]:
        latest = {op.opportunity_id: op for op in self.legacy_ops}
        for row in self.rows:
            for raw in row['opportunities']:
                op = Opportunity.model_validate(raw)
                latest[op.opportunity_id] = op
        return list(latest.values())

    def checkpoint(self, run: RunRecord, ops: list[Opportunity]) -> None:
        # Revalidate mutable models before serialization. Never persist raw candidates.
        canonical = [Opportunity.model_validate(op.model_dump()) for op in ops]
        if len({op.opportunity_id for op in canonical}) != len(canonical):
            raise StateError('duplicate_finalized_opportunity')
        if any(op.status == 'candidate' for op in canonical):
            raise StateError('unfinished_candidate')
        row = {'run': RunRecord.model_validate(run.model_dump()).model_dump(),
               'opportunities': [op.model_dump() for op in canonical]}
        rows = [r for r in self.rows if r['run']['run_id'] != run.run_id] + [row]
        serialized = ''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n' for r in rows)
        atomic_write(self.path, serialized)
        self.rows = rows


from contextlib import contextmanager

@contextmanager
def exclusive_writer(root: Path):
    # Scout runs on Linux GitHub Actions. flock releases automatically on death;
    # no stale-lock deletion heuristics and no database/service dependency.
    import fcntl
    path = root/'state'/'.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StateError('another_writer_active') from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
