"""Offline strategy playbooks for a better Scout innovation/research brief.

These are QUESTIONS and possible differentiation mechanisms, not verified
solutions, buyer demand, existing technology deployments or market conclusions.
The paid research brain can later challenge these alternatives with citations.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import Opportunity
from .state import Store, atomic_write

PLAYBOOKS = {
    "ecommerce_niches": [
        "Target a specific neglected customer subgroup with a measurable unmet product requirement.",
        "Compare imported/private-label, inventoryless fulfillment and existing domestic suppliers after landed costs.",
        "Test one narrower search/intention channel before expanding catalog or buying inventory.",
    ],
    "geographic_arbitrage": [
        "Test a foreign-proven product with verifiable Chilean competitor coverage and local price/feature comparisons.",
        "Localise distribution, after-sales support or financing rather than merely translating a product.",
        "Use an authorised small supplier quote and real buyer signal before import.",
    ],
    "chile_localization": [
        "Find the smallest Chilean workflow whose economics differ from the original geography.",
        "Secure lawful access, partners and after-sales support rather than copy protected technology.",
        "Run a buyer interview or mock listing to falsify assumptions before capital commitment.",
    ],
    "innovation_adoption": [
        "Identify a real technical capability not yet adopted in one buyer's high-value workflow.",
        "Create a repeatable owned product/data/workflow asset rather than one-off AI agency services.",
        "Measure the fully loaded operating cost, human exceptions and distribution against the status quo.",
    ],
    "competitive_positioning": [
        "Segment the incumbent market by customers who pay too much or wait too long for one outcome.",
        "Offer materially different positioning, delivery, price or specialisation with clear unit economics.",
        "Test switching and repeat purchase evidence before scaling acquisition.",
    ],
    "physical_distribution": [
        "Compare local product availability to supplier catalogs and independent consumer interest.",
        "Check import, tax, return, certification and delivery economics before estimating margin.",
        "Try a legitimate pre-order/waitlist test with transparent fulfillment conditions.",
    ],
    "robotics_agritech": [
        "Explore robotic equipment leasing versus local distribution versus managed equipment operation.",
        "Model local labor savings, duty cycles, repair/parts logistics and farm-scale constraints.",
        "Arrange a bounded field validation with an actual farm operator before scaling.",
    ],
    "energy_infrastructure": [
        "Identify a specific off-taker, grid bottleneck or paying industrial load in Chile.",
        "Compare owned asset, installer/distributor and project-finance participation.",
        "Verify permits and installed net payback under conservative power price scenarios.",
    ],
    "asymmetric_investing": [
        "Form an early-adoption or balance-sheet hypothesis with dated primary disclosures.",
        "Contrast current valuation with realistic downside dilution, illiquidity and contrary catalysts.",
        "Build a watchlist of falsifiable milestones; never buy from an unreviewed alert.",
    ],
    "public_markets": [
        "Find overlooked fundamentals and a named accessible security with dated primary filings.",
        "Compare risked intrinsic value, market expectations and specific downside scenarios.",
        "Define catalysts and invalidation thresholds before any governed investment decision.",
    ],
    "open_finance_chile": [
        "Choose an exact consented-data workflow and regulated payer, not general fintech implementation.",
        "Check license perimeter, API access, legal compliance and competitor pricing.",
        "Test buyer procurement and technical access before writing integration infrastructure.",
    ],
    "general": [
        "Name a specific payer, customer job and credible reason existing alternatives fail.",
        "Choose a low-cost differentiation wedge (availability, price, experience, distribution or technology).",
        "Test channel, willingness to pay, ownership and contribution margin before building.",
    ],
}


def innovation_brief(op: Opportunity) -> dict:
    if not isinstance(op, Opportunity):
        raise TypeError("CANONICAL_SCOUT_OPPORTUNITY_REQUIRED")
    alternatives = PLAYBOOKS.get(op.vertical, PLAYBOOKS["general"])
    if not op.value_capture_mechanism.strip() or not op.participation_path.strip():
        alternatives = PLAYBOOKS["general"]
    gaps = list(dict.fromkeys(op.unknowns + op.falsification_conditions))
    if not gaps:
        gaps = ["Who is the actual payer and what evidence establishes demand?",
                "What existing alternative already solves this job?",
                "What is net contribution after fulfillment, fees, support and acquisition?"]
    return {
        "opportunity_id": op.opportunity_id,
        "name": op.name,
        "status": op.status,
        "research_only": True,
        "commercially_validated": False,
        "investment_authorized": False,
        "category": op.vertical,
        "geography": op.geography,
        "current_thesis": op.thesis,
        "value_capture_claim": op.value_capture_mechanism,
        "current_participation_path": op.participation_path,
        "strategy_hypotheses_not_facts": list(alternatives),
        "hypothesis_evaluation_questions": list(gaps)[:7],
        "proposed_first_action": "Independently confirm sources and validate one real customer or market participant without economic commitments.",
        "capital_required_unverified_estimate": op.capital_required,
        "founder_hours_initial_unverified_estimate": op.diego_hours_initial,
        "founder_hours_ongoing_unverified_estimate": op.diego_hours_ongoing,
        "time_horizon_unverified_estimate": op.time_horizon,
        "supporting_source_urls": [e.url for e in op.evidence if e.grounded],
        "competition_confirmed": False, "willingness_to_pay_confirmed": False,
        "pricing_confirmed": False, "regulatory_access_confirmed": False,
    }


def write_innovation_backlog(root: Path, opportunities: list[Opportunity] | None = None) -> dict:
    if opportunities is None:
        opportunities = Store(root).opportunities()
    briefs = [innovation_brief(o) for o in opportunities if o.status in ("survived", "watch")]
    briefs.sort(key=lambda b: (0 if b["status"] == "survived" else 1,
                               b["category"], b["name"].casefold(), b["opportunity_id"]))
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commercially_validated_count": 0,
        "source": "CANONICAL_SCOUT_WATCH_AND_SURVIVOR_RESEARCH",
        "purpose": "Falsifiable business differentiation, innovation, investment and Chilean localisation research assignments.",
        "briefs": briefs,
    }
    folder = root/"reports"
    atomic_write(folder/"innovation_backlog.json",
                 json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+"\n")
    lines = ["# Scout V1 — Innovation and positioning research backlog", "",
             "Not evidence of buyers, a priced offer, regulatory access or a profitable asset.", "",
             "Candidates: " + str(len(briefs)), ""]
    for b in briefs:
        def sanitize(s):
            return " ".join(str(s).split()).replace("<", "‹").replace(">", "›").rstrip()
        lines.extend(["## " + sanitize(b["name"]),
                      "- Status: " + b["status"] + " | " + b["category"],
                      "- Current idea: " + sanitize(b["current_thesis"]),
                      "- Potential economic capture: " + sanitize(b["value_capture_claim"]),
                      "- **Research routes to test (NOT validated claims):**"] +
                     ["  - " + sanitize(x) for x in b["strategy_hypotheses_not_facts"]] +
                     ["- Critical gaps: " + "; ".join(sanitize(x) for x in b["hypothesis_evaluation_questions"][:3]),
                      "- Possible initial budget: " + sanitize(b["capital_required_unverified_estimate"]),
                      "- Source URLs: " + "; ".join(b["supporting_source_urls"][:4]), ""])
    atomic_write(folder/"innovation_backlog.md", "\n".join(line.rstrip() for line in lines).rstrip()+"\n")
    return {"research_briefs": len(briefs),
            "commercially_validated_count": 0,
            "paths": ["reports/innovation_backlog.json", "reports/innovation_backlog.md"]}
