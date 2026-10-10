"""Zero-cost commercial falsification queue from existing Scout research.

A candidate is never promoted to a real business, a verified buyer, a sale,
or an authorised outreach operation by sorting it. This is a *review queue*
designed to concentrate scarce founder hours on first-dollar proof.
"""
from __future__ import annotations

import json
from pathlib import Path

from .state import atomic_write


# Reuse narrow research theses rather than manufacturing fresh market claims.
# General macro narratives and securities are deliberately excluded from the
# first-dollar product queue. Any candidate can still remain in Scout's library.
PRODUCT_VERTICALS = (
    "ecommerce_niches",
    "chile_localization",
    "open_finance_chile",
    "energy_infrastructure",
    "robotics_agritech",
    "innovation_adoption",
)
SPECIFIC_WEDGE_WORDS = (
    "kit", "test", "harness", "pre-check", "recovery",
    "conformance", "tool", "template", "product", "asset",
)
BUYER_TESTS = {
    "ecommerce_niches": (
        "Select one specific product/problem. Verify alternatives, landed or "
        "fulfilment costs, return/refund exposure, and whether a real buyer "
        "would pay; no store launch or supplier order is authorised."
    ),
    "chile_localization": (
        "Compare at least three real Chilean substitutes and published prices. "
        "Verify a legally deliverable owned product and obtain independent "
        "buyer interest before any stock, ads or paid accounts."
    ),
    "open_finance_chile": (
        "Identify one genuinely budget-owning regulated buyer, one conformance "
        "failure, and an independently accepted paid software deliverable "
        "before coding a broad financial integration."
    ),
    "energy_infrastructure": (
        "Obtain a buyer's actual equipment/inspection requirement, a real "
        "supplier cost and applicable Chilean regulatory conditions first."
    ),
    "robotics_agritech": (
        "Find a real operator's measured baseline and proposed savings, plus "
        "equipment/installation prices, before a product or pilot."
    ),
    "innovation_adoption": (
        "Find one repeatable, owned product with a named buyer and a measurable "
        "job the buyer agrees to purchase; do not offer an AI agency service."
    ),
}
MISSING_PROOFS = (
    "independent_specific_buyer",
    "written_price_or_paid_commitment",
    "verified_fulfilment_and_unit_cost",
    "distribution_permission_or_channel",
    "actual_third_party_receipt",
)


def _simple(text: object, size: int = 260) -> str:
    """Model text is untrusted, including Markdown and provider snippets."""
    return " ".join(str(text or "").split())[:size].replace("<", "‹").replace(
        ">", "›").replace("|", "¦").replace("[", "⟦").replace("]", "⟧")


def _evidence_count(card: dict) -> int:
    return sum(
        e.get("grounded_in_provider_search") is True
        and e.get("source_type") in {"primary", "independent"}
        for e in card.get("evidence", [])
        if isinstance(e, dict)
    )


def commercial_review_queue(library: dict, *, maximum: int = 4) -> dict:
    if not isinstance(library, dict) or library.get("source") != "SCOUT_CANONICAL_PERSISTED_STATE":
        raise ValueError("CANONICAL_SCOUT_LIBRARY_REQUIRED")
    if type(maximum) is not int or not 1 <= maximum <= 20:
        raise ValueError("INVALID_COMMERCIAL_REVIEW_SIZE")
    candidates = []
    for card in library.get("cards", []):
        if not isinstance(card, dict) or card.get("status") not in ("watch", "survived"):
            continue
        vertical = card.get("vertical")
        if vertical not in PRODUCT_VERTICALS:
            continue
        if card.get("critic_reviewed") is not True or card.get("judge_reviewed") is not True:
            continue
        if _evidence_count(card) < 2 or not str(card.get("participation_path", "")).strip():
            continue
        title = str(card.get("title", "")).lower()
        narrow = any(word in title for word in SPECIFIC_WEDGE_WORDS)
        if not narrow:
            # Generic regulation or technology trends belong in the research
            # library, NOT a first-dollar buyer test worklist.
            continue
        chilean = "chile" in str(card.get("geography", "")).lower() or "chile" in title
        score = (
            int(chilean),
            _evidence_count(card),
            int(card.get("status") == "survived"),
            -PRODUCT_VERTICALS.index(vertical),
        )
        candidates.append((score, card))

    candidates.sort(key=lambda pair: (
        tuple(-n for n in pair[0]), pair[1]["title"].casefold(), pair[1]["id"]
    ))
    selected, used_verticals = [], set()
    for _, card in candidates:
        vertical = card["vertical"]
        if vertical in used_verticals:
            continue
        used_verticals.add(vertical)
        selected.append({
            "opportunity_id": card["id"],
            "title": card["title"],
            "vertical": vertical,
            "origin": "EXISTING_SCOUT_WATCH_OR_SURVIVOR_NOT_NEW_OPPORTUNITY",
            "current_status": card["research_status"],
            "economic_status": "UNVALIDATED_NO_VERIFIED_BUYER_OR_SALE",
            "buyer_verified": False,
            "revenue_verified": False,
            "automatic_outreach_authorized": False,
            "automatic_purchase_authorized": False,
            "next_no_spend_buyer_test": BUYER_TESTS[vertical],
            "first_distribution_hypothesis": card["participation_path"],
            "verified_source_urls": [
                e["url"] for e in card["evidence"]
                if isinstance(e, dict) and e.get("grounded_in_provider_search") is True
            ][:4],
            "missing_to_prove": list(MISSING_PROOFS),
        })
        if len(selected) >= maximum:
            break
    return {
        "schema_version": 1,
        "source": "SCOUT_CANONICAL_DERIVED_LIBRARY_NO_NEW_MARKET_EVIDENCE",
        "generated_at": library["generated_at"],
        "selection_type": "FOUNDER_REVIEW_QUEUE_NOT_AUTONOMOUS_ECONOMIC_EXECUTION",
        "first_dollar_verified": False,
        "buyer_qualified_count": 0,
        "revenue_usd_verified": None,
        "opportunity_count_reviewed": len(library["cards"]),
        "selected": selected,
        "excluded_from_first_dollar_queue": len(library["cards"]) - len(selected),
        "warning": "Heuristic triage only. All buyer, unit-margin, channel, and sale claims require external independent validation.",
    }


def render_commercial_queue(report: dict) -> str:
    lines = [
        "# Scout — first-dollar customer validation queue",
        "",
        "Research assignment only. **Zero verified buyers, sales, or execution permissions.**",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Research cards reviewed: {report['opportunity_count_reviewed']}",
        f"- Narrow ideas selected for founder review: {len(report['selected'])}",
        "- Verified third-party receipts: **none**",
        "",
    ]
    for index, card in enumerate(report["selected"], 1):
        lines.extend([
            f"## {index}. {_simple(card['title'], 145)}",
            f"- Origin: existing Scout research; {_simple(card['vertical'])}; no new opportunity claim",
            f"- Next falsifiable no-spend test: {_simple(card['next_no_spend_buyer_test'], 430)}",
            f"- Distribution hypothesis (not verified): {_simple(card['first_distribution_hypothesis'], 430)}",
            "- Missing: independent buyer, credible paid price, all-in contribution margin, lawful channel, real receipt",
            "- Sources: " + "; ".join(_simple(u, 195) for u in card["verified_source_urls"]),
            "- Status: **WATCH — no automated outreach, spending, or execution**",
            "",
        ])
    if not report["selected"]:
        lines.append("No credible narrow first-dollar test survived deterministic triage. Do not invent one.")
    return "\n".join(lines).rstrip() + "\n"


def write_commercial_queue(root: Path, library: dict) -> dict:
    """Produce customer validation shortlist without model, web or provider calls."""
    report = commercial_review_queue(library)
    folder = Path(root) / "reports"
    atomic_write(folder / "commercial_queue.json",
                 json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True,
                            allow_nan=False) + "\n")
    atomic_write(folder / "commercial_queue.md", render_commercial_queue(report))
    return {
        "research_queue_count": len(report["selected"]),
        "verified_buyers": 0,
        "verified_external_revenue": False,
        "files": ["reports/commercial_queue.json", "reports/commercial_queue.md"],
    }
