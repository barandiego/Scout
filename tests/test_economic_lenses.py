"""No-network checks for economically useful, non-paid Scout discovery lenses."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_economic_lenses_keep_variety_and_no_duplicate_ids():
    data = yaml.safe_load((ROOT / "config" / "lenses.yaml").read_text(encoding="utf-8"))
    lenses = data["lenses"]
    ids = [entry["id"] for entry in lenses]
    assert len(ids) == len(set(ids))
    for required in ("remote_paid_evaluation", "inventoryless_product_validation",
                     "fixed_scope_paid_research_asset", "public_markets",
                     "geographic_arbitrage", "wildcard"):
        assert required in ids
    assert all(isinstance(item["prompt"], str) and len(item["prompt"]) >= 35
               for item in lenses)


def test_no_expansion_of_existing_paid_budget_or_review_calls():
    cfg = yaml.safe_load((ROOT / "config" / "scout.yaml").read_text(encoding="utf-8"))
    assert cfg["budget"]["cycle_usd"] <= 0.08
    assert cfg["budget"]["daily_usd"] <= 0.50
    assert cfg["limits"]["lenses_per_cycle"] == 3
    assert cfg["limits"]["max_candidates_to_critic"] == 1
    assert cfg["limits"]["max_candidates_to_judge"] == 1


def test_remote_work_lens_demands_truthful_external_payment_evidence():
    data = yaml.safe_load((ROOT / "config" / "lenses.yaml").read_text(encoding="utf-8"))
    prompt = next(lens["prompt"] for lens in data["lenses"]
                  if lens["id"] == "remote_paid_evaluation").lower()
    for term in ("chile", "eligibility", "application", "payout", "age"):
        assert term in prompt
