"""Offline-only prototype: atomic publication of a validated monitor result.

Not integrated with workflows. Caller must create a unique report before
launch and provide exclusive writer access.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime
from pathlib import Path

from .procurement_completion import CompletionError, validate_completion
from .state import atomic_write

MARKER = Path("state/public_procurement_chile/pending.json")
STATE = Path("state/public_procurement_chile/events.jsonl")
REPORT = Path("reports/public_procurement_chile/latest.json")


class FinalizeError(RuntimeError):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=root, text=True,
                                capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FinalizeError("git_unavailable_or_timed_out") from exc
    if result.returncode:
        raise FinalizeError("git_operation_failed")
    return result.stdout.strip()


def finalize(root: Path, *, report: Path, run_id: str, exit_code: int,
             started_at: datetime) -> dict:
    """Commit state, report and marker removal together, rejecting stale HEAD.

    A rejected push leaves the previously published marker on origin. Local
    work may require cleanup; never retry an API request based on local state.
    Caller must arrange exclusive writing and ensure the run-scoped report
    did not exist before the invocation began.
    """
    root = root.resolve()
    if not isinstance(run_id, str) or not run_id.isdecimal():
        raise FinalizeError("invalid_run_id")
    expected = root / ".procurement-runs" / (run_id + ".json")
    if report.is_symlink() or report.resolve() != expected.resolve():
        raise FinalizeError("report_not_run_scoped")
    marker, state = root / MARKER, root / STATE
    if marker.is_symlink() or state.is_symlink():
        raise FinalizeError("unsafe_state_path")
    if not state.is_file():
        raise FinalizeError("state_missing")
    if _git(root, "diff", "--cached", "--name-only"):
        raise FinalizeError("staged_changes_present")
    head = _git(root, "rev-parse", "HEAD")
    if _git(root, "ls-remote", "origin", "refs/heads/main") != head + "\trefs/heads/main":
        raise FinalizeError("remote_head_changed")
    try:
        published_marker = _git(root, "show", "HEAD:" + MARKER.as_posix())
        current_marker = marker.read_text(encoding="utf-8").strip()
        if published_marker != current_marker:
            raise FinalizeError("marker_not_published")
    except (OSError, UnicodeError):
        raise FinalizeError("marker_unreadable") from None
    try:
        receipt = validate_completion(marker=marker, report=report, state=state,
                                      run_id=run_id, exit_code=exit_code,
                                      started_at=started_at)
    except CompletionError as exc:
        raise FinalizeError("completion_unverifiable") from exc
    report_bytes = report.read_bytes()
    state_bytes = state.read_bytes() if state.exists() else None
    if hashlib.sha256(report_bytes).hexdigest() != receipt["report_sha256"]:
        raise FinalizeError("report_changed")
    current_state = hashlib.sha256(state_bytes).hexdigest() if state_bytes is not None else None
    if current_state != receipt["state_sha256"]:
        raise FinalizeError("state_changed")
    atomic_write(root / REPORT, report_bytes.decode("utf-8"))
    os.unlink(marker)
    paths = [REPORT.as_posix(), MARKER.as_posix()]
    if state.exists():
        paths.append(STATE.as_posix())
    _git(root, "add", "-A", "--", *paths)
    _git(root, "commit", "-m", "chore: persist controlled procurement completion")
    _git(root, "push", "origin", "HEAD:refs/heads/main")
    return receipt
