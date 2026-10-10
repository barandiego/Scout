"""Scout library: free, deterministic, safe, honest economic-readiness labels."""
import json
from datetime import datetime, timezone

import pytest

from scout.library import build_snapshot, render_markdown, write_library
from scout.models import Opportunity, RunRecord
from scout.state import StateError, Store


NOW = "2026-10-09T23:00:00+00:00"


def opportunity(name, status="watch", **fields):
    defaults = dict(
        opportunity_id="id-" + name.lower().replace(" ", "-"),
        discovered_at=NOW, last_updated=NOW, name=name,
        type="software", vertical="general", geography="Chile",
        signal="New customer job", what_changed="New procurement route",
        why_now="New procurement route", thesis="There may be an underserved market",
        value_capture_mechanism="Recurring subscription if real buyers pay",
        participation_path="Interview possible buyers before writing any software",
        status=status, actionable=True,
        unknowns=["Do buyers have budget?", "How much would customers pay?"],
        critic_reviewed=True, judge_reviewed=True, evidence_confidence=0.73,
    )
    defaults.update(fields)
    return Opportunity(**defaults)


def test_watch_is_research_not_a_ready_money_making_idea():
    card = build_snapshot([opportunity("Example A")], generated_at=NOW)["cards"][0]
    assert card["authorized_for_execution"] is False
    assert card["research_status"] == "WATCH_REQUIRES_VALIDATION"
    assert card["next_validation_questions"][0] == "Do buyers have budget?"
    assert "external_buyer_and_unit_economics_validation" in card["missing_execution_proof"]


def test_no_hallucinated_validation_or_survivor():
    snapshot = build_snapshot(
        [opportunity("A"), opportunity("R", status="rejected")],
        generated_at=NOW)
    assert snapshot["watch"] == 1 and snapshot["rejected_excluded"] == 1
    assert snapshot["survived"] == snapshot["execution_authorized"] == 0
    assert snapshot["external_revenue_verified"] is False
    assert len(snapshot["cards"]) == 1


def test_deduplicate_identical_ids_without_mutating_authoritative_history():
    a = opportunity("A")
    later = a.model_copy(update={"decision_reason": "Reviewed later"})
    snap = build_snapshot([a, later], generated_at=NOW)
    assert snap["total_distinct_opportunities"] == 1
    assert snap["cards"][0]["judgment"] == "Reviewed later"
    assert a.decision_reason != "Reviewed later"


def test_corrupt_state_blocks_export_instead_of_inventing_records(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "transactions.jsonl").write_text("{BROKEN\n", encoding="utf-8")
    with pytest.raises(StateError):
        write_library(tmp_path)
    assert not (tmp_path / "reports" / "library.json").exists()


def test_store_round_trip_emits_both_usable_catalogue_files(tmp_path):
    store = Store(tmp_path)
    rec = RunRecord(run_id="run_catalogue", started_at=NOW, finished_at=NOW,
                    mode="cycle", ok=True, outcome="SUCCESS")
    store.checkpoint(rec, [opportunity("Pilot candidate")])
    info = write_library(tmp_path)
    parsed = json.loads((tmp_path / "reports" / "library.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "reports" / "library.md").read_text(encoding="utf-8")
    assert info["cards"] == 1
    assert parsed["cards"][0]["id"] == "id-pilot-candidate"
    assert "Do buyers have budget?" in markdown
    assert "Autonomous execution authorization: 0" in markdown


def test_rendering_does_not_allow_model_authored_html_in_report():
    op = opportunity("Unsafe <script>example</script>")
    snap = build_snapshot([op], generated_at=NOW)
    md = render_markdown(snap)
    assert "<script>" not in md
    assert "‹script›" in md


def test_timezone_required_and_unvalidated_input_rejected():
    with pytest.raises(ValueError):
        build_snapshot([], generated_at="2026-10-09T12:00:00")
    with pytest.raises(TypeError):
        build_snapshot([{"status": "survived"}], generated_at=NOW)
