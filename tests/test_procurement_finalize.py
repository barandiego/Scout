import json
from datetime import datetime, timezone

import pytest

from scout import procurement_finalize as final

START = datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)
HEAD = "a" * 40


@pytest.fixture
def env(tmp_path, monkeypatch):
    marker = tmp_path / final.MARKER
    marker.parent.mkdir(parents=True)
    (tmp_path / final.STATE).write_text('', encoding='utf-8')
    marker.write_text(json.dumps({"schema": 1, "run_id": "42"}), encoding="utf-8")
    report = tmp_path / ".procurement-runs" / "42.json"
    report.parent.mkdir()
    report.write_text(json.dumps({
        "generated_at": "2026-10-28T10:00:01Z", "ok": False,
        "outcome": "DEGRADED_INCOMPLETE_SOURCE_WINDOW",
        "diagnostics": {"api_failures": {}, "detail_cap_exhausted": True}
    }), encoding="utf-8")
    calls = []
    def fake_git(root, *args):
        calls.append(args)
        if args[:2] == ("rev-parse", "--show-object-format"):
            return "sha1"
        if args[:1] == ("rev-parse",) and args[1].startswith(":"):
            return final._blob_id((tmp_path / args[1][1:]).read_bytes())
        if args[:1] == ("rev-parse",):
            return HEAD
        if args[:3] == ("diff", "--cached", "--name-status"):
            return "D\t" + final.MARKER.as_posix()
        if args[:1] == ("ls-remote",):
            return HEAD + "\trefs/heads/main"
        if args[:1] == ("show",):
            return marker.read_text(encoding="utf-8").strip()
        return ""
    monkeypatch.setattr(final, "_git", fake_git)
    return tmp_path, marker, report, calls


def run(env):
    root, marker, report, calls = env
    return final.finalize(root, report=report, run_id="42", exit_code=2,
                          started_at=START)


def test_known_degraded_result_commits_report_and_marker_removal_together(env):
    root, marker, report, calls = env
    receipt = run(env)
    assert receipt["run_id"] == "42"
    assert not marker.exists()
    assert json.loads((root / final.REPORT).read_text())["ok"] is False
    add = next(call for call in calls if call[0] == "add")
    assert final.REPORT.as_posix() in add
    assert final.MARKER.as_posix() in add
    assert [call[0] for call in calls][-2:] == ["commit", "push"]
    assert calls.index(add) < next(i for i, call in enumerate(calls) if call[0] == "commit")


def test_changed_remote_blocks_before_marker_or_report_mutation(env, monkeypatch):
    root, marker, report, calls = env
    original = final._git
    def changed(root, *args):
        if args[0] == "ls-remote":
            return "b" * 40 + "\trefs/heads/main"
        return original(root, *args)
    monkeypatch.setattr(final, "_git", changed)
    with pytest.raises(final.FinalizeError, match="remote_head_changed"):
        run(env)
    assert marker.exists()
    assert not (root / final.REPORT).exists()


def test_missing_cooldown_blocks_rate_limit_completion(env):
    root, marker, report, calls = env
    data = json.loads(report.read_text())
    data["outcome"] = "DEGRADED_API_ERRORS"
    data["diagnostics"] = {"api_failures": {"api_rate_limited": 1}}
    report.write_text(json.dumps(data))
    with pytest.raises(final.FinalizeError, match="completion_unverifiable"):
        run(env)
    assert marker.exists()
    assert not any(call[0] == "push" for call in calls)


def test_failed_push_does_not_report_success(env, monkeypatch):
    root, marker, report, calls = env
    original = final._git
    def fail_push(root, *args):
        if args[0] == "push":
            raise final.FinalizeError("git_operation_failed")
        return original(root, *args)
    monkeypatch.setattr(final, "_git", fail_push)
    with pytest.raises(final.FinalizeError, match="git_operation_failed"):
        run(env)


def test_report_must_be_run_scoped(env):
    root, marker, report, calls = env
    other = root / "other.json"
    other.write_text(report.read_text())
    with pytest.raises(final.FinalizeError, match="report_not_run_scoped"):
        final.finalize(root, report=other, run_id="42", exit_code=2, started_at=START)
    assert marker.exists()


def test_report_change_after_validation_blocks(env, monkeypatch):
    root, marker, report, calls = env
    validate = final.validate_completion
    def tampered(**kwargs):
        receipt = validate(**kwargs)
        report.write_text('{"changed":true}', encoding="utf-8")
        return receipt
    monkeypatch.setattr(final, "validate_completion", tampered)
    with pytest.raises(final.FinalizeError, match="report_changed"):
        run(env)
    assert marker.exists()
    assert not any(call[0] == "push" for call in calls)


def test_unexpected_staged_changes_block(env, monkeypatch):
    root, marker, report, calls = env
    original = final._git
    def staged(root, *args):
        if args[:3] == ("diff", "--cached", "--name-only"):
            return "unrelated.txt"
        return original(root, *args)
    monkeypatch.setattr(final, "_git", staged)
    with pytest.raises(final.FinalizeError, match="staged_changes_present"):
        run(env)
    assert marker.exists()


def test_marker_must_match_published_head(env, monkeypatch):
    root, marker, report, calls = env
    original = final._git
    def different(root, *args):
        if args[0] == "show":
            return '{"schema": 1, "run_id": "different"}'
        return original(root, *args)
    monkeypatch.setattr(final, "_git", different)
    with pytest.raises(final.FinalizeError, match="marker_not_published"):
        run(env)
    assert marker.exists()
    assert not any(call[0] == "push" for call in calls)


def test_git_timeout_is_reported_as_failure(tmp_path, monkeypatch):
    import subprocess
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 15)
    monkeypatch.setattr(final.subprocess, "run", timeout)
    with pytest.raises(final.FinalizeError, match="git_unavailable_or_timed_out"):
        final._git(tmp_path, "push", "origin", "HEAD:refs/heads/main")


def test_missing_state_cannot_be_reported_as_durable(env):
    root, marker, report, calls = env
    (root / final.STATE).unlink()
    with pytest.raises(final.FinalizeError, match="state_missing"):
        run(env)
    assert marker.exists()
    assert not any(call[0] == "push" for call in calls)

@pytest.mark.parametrize("target", ["state", "report"])
def test_changed_staged_bytes_block_commit_and_push(env, monkeypatch, target):
    root, marker, report, calls = env
    original = final._git
    def race(root, *args):
        if args[0] == "add":
            path = root / (final.STATE if target == "state" else final.REPORT)
            path.write_text("changed after validation", encoding="utf-8")
        return original(root, *args)
    monkeypatch.setattr(final, "_git", race)
    with pytest.raises(final.FinalizeError, match="staged_evidence_changed"):
        run(env)
    assert not any(call[0] in ("commit", "push") for call in calls)


def test_missing_staged_marker_deletion_blocks_commit(env, monkeypatch):
    root, marker, report, calls = env
    original = final._git
    def missing_deletion(root, *args):
        if args[:3] == ("diff", "--cached", "--name-status"):
            return ""
        return original(root, *args)
    monkeypatch.setattr(final, "_git", missing_deletion)
    with pytest.raises(final.FinalizeError, match="marker_deletion_not_staged"):
        run(env)
    assert not any(call[0] in ("commit", "push") for call in calls)


def test_blob_id_matches_real_git_index(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    data = '{"observacion":"válida"}\n'.encode("utf-8")
    (tmp_path / "record.json").write_bytes(data)
    subprocess.run(["git", "-c", "core.autocrlf=false", "add", "record.json"],
                   cwd=tmp_path, check=True)
    result = subprocess.run(["git", "rev-parse", ":record.json"], cwd=tmp_path,
                            text=True, capture_output=True, check=True)
    assert result.stdout.strip() == final._blob_id(data)
