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
# Constrained to product-level evidence: "production infrastructure" and
# "integration testing market" do not make a narrow sellable product.
SPECIFIC_WEDGES = {
    "ecommerce_niches": ("returns-recovery", "returns recovery", "product kit", "sku test"),
    "chile_localization": ("kit", "localization product"),
    "open_finance_chile": ("conformance test", "conformance-test", "test harness", "test asset"),
    "energy_infrastructure": ("pre-check", "compliance kit"),
    "robotics_agritech": ("audit wedge", "product kit", "equipment test"),
    "innovation_adoption": ("product kit", "software tool", "test harness"),
}
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


def _grounded_source_urls(card: dict) -> list[str]:
    """Count only unique, nonempty provider-grounded primary/independent URLs.

    Multiple claims supported by the same URL do not create independent
    source evidence. This is URL deduplication, not a claim-truth judgment.
    """
    seen, urls = set(), []
    for evidence in card.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        if evidence.get("grounded_in_provider_search") is not True:
            continue
        if evidence.get("source_type") not in {"primary", "independent"}:
            continue
        url = evidence.get("url")
        if not isinstance(url, str):
            continue
        url = url.strip()
        if not url.startswith(("https://", "http://")) or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _evidence_count(card: dict) -> int:
    return len(_grounded_source_urls(card))


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
        reviewed = card.get("critic_reviewed") is True and card.get("judge_reviewed") is True
        if _evidence_count(card) < 2 or not str(card.get("participation_path", "")).strip():
            continue
        title = str(card.get("title", "")).lower()
        narrow = any(word in title for word in SPECIFIC_WEDGES[vertical])
        if not narrow:
            # Generic regulation or technology trends belong in the research
            # library, NOT a first-dollar buyer test worklist.
            continue
        # Source-backed unreviewed records may be proposed for *review*, not
        # execution. Hiding them would let a generic reviewed macro thesis
        # displace more falsifiable product hypotheses.
        score = (
            int(reviewed),
            _evidence_count(card),
        )
        candidates.append((score, card))

    selected, used_verticals = [], set()
    for vertical in PRODUCT_VERTICALS:
        choices = [(score, card) for score, card in candidates
                   if card["vertical"] == vertical]
        choices.sort(key=lambda pair: (
            tuple(-n for n in pair[0]), pair[1]["title"].casefold(), pair[1]["id"]
        ))
        if not choices:
            continue
        _, card = choices[0]
        used_verticals.add(vertical)
        reviewed = card.get("critic_reviewed") is True and card.get("judge_reviewed") is True
        selected.append({
            "opportunity_id": card["id"],
            "title": card["title"],
            "vertical": vertical,
            "origin": "EXISTING_SCOUT_WATCH_OR_SURVIVOR_NOT_NEW_OPPORTUNITY",
            "current_status": card["research_status"],
            "economic_status": "UNVALIDATED_NO_VERIFIED_BUYER_OR_SALE",
            "independent_review_status": (
                "CRITIC_JUDGE_COMPLETE_NOT_COMMERCIAL_PROOF" if reviewed
                else "REVIEW_PENDING_DO_NOT_PROMOTE"
            ),
            "buyer_verified": False,
            "revenue_verified": False,
            "automatic_outreach_authorized": False,
            "automatic_purchase_authorized": False,
            "next_no_spend_buyer_test": BUYER_TESTS[vertical],
            "first_distribution_hypothesis": card["participation_path"],
            "verified_source_urls": _grounded_source_urls(card)[:4],
            "missing_to_prove": (
                ([] if reviewed else ["independent_critic_and_judge"]) + list(MISSING_PROOFS)
            ),
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
            "- Independent critic/judge: " + card["independent_review_status"],
            "- Missing: " + ", ".join(card["missing_to_prove"]),
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
