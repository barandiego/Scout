"""Read-only thematic focus report for Scout HQ.

One theme is NOT the same as one economic opportunity. Never erase, reject,
promote, or merge canonical records using this report. No provider calls.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from .state import atomic_write


def _words(value: object) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def theme(card: dict) -> str:
    """Coarse editorial theme, not identity, similarity or duplicate proof."""
    title = _words(card.get("title", ""))
    vertical = _words(card.get("vertical", ""))
    if vertical == "open finance chile" or any(
        phrase in title for phrase in ("open finance", "finanzas abiertas", "consent flow")
    ):
        return "chile_open_finance"
    if "sfa" in title.split():
        return "chile_open_finance"
    if "nfc" in title or "contactless card" in title:
        return "nfc_products"
    if any(term in title for term in ("robotic weed", "robot weeding", "mechanical weeding", "desmalez")):
        return "agricultural_weeding_robots"
    if "data center" in title or "data centre" in title:
        return "data_center_infrastructure"
    if any(term in title for term in ("battery", "bess", "grid", "electric", "power", "energy", "energia")):
        return "energy_infrastructure"
    if any(term in title for term in ("ocr", "document extraction", "document parsing")):
        return "document_extraction"
    if any(term in title for term in ("agent security", "agent attack", "pre spend", "prompt injection")):
        return "agent_security"
    # Generic verticals have unrelated technologies. Avoid collapsing all
    # 'general' or all 'public_markets' cards into a single pseudo-idea.
    tokens = [x for x in title.split() if x not in {
        "the", "a", "for", "and", "with", "in", "of", "to", "on", "from",
        "chile", "chilean", "using", "as", "is", "new", "an", "its",
    }]
    return (vertical or "unknown").replace(" ", "_") + ":" + "_".join(tokens[:3])


def _quality(card: dict) -> tuple:
    # Presentation only; these signals do NOT certify source truth or sales.
    reviewed = bool(card.get("critic_reviewed") and card.get("judge_reviewed"))
    evidence = card.get("evidence")
    grounded = sum(bool(e.get("grounded_in_provider_search"))
                   for e in evidence if isinstance(e, dict)) if isinstance(evidence, list) else 0
    return (-int(card.get("status") == "survived"), -int(reviewed),
            -grounded, str(card.get("discovered_at", "")), str(card.get("id", "")))


def build_focus(library: dict, *, max_headlines: int = 12) -> dict:
    """Produce one editorial representative per theme without discarding data."""
    if not isinstance(library, dict) or library.get("source") != "SCOUT_CANONICAL_PERSISTED_STATE":
        raise ValueError("CANONICAL_LIBRARY_REQUIRED")
    cards = library.get("cards")
    if not isinstance(cards, list) or any(not isinstance(c, dict) for c in cards):
        raise ValueError("INVALID_LIBRARY_CARDS")
    if not isinstance(max_headlines, int) or isinstance(max_headlines, bool) or not 1 <= max_headlines <= 100:
        raise ValueError("INVALID_HEADLINE_LIMIT")
    groups: dict[str, list[dict]] = defaultdict(list)
    for card in cards:
        if not card.get("id") or not card.get("title"):
            raise ValueError("INCOMPLETE_CANONICAL_CARD")
        groups[theme(card)].append(card)
    sorted_groups = [(key, sorted(items, key=_quality)) for key, items in groups.items()]
    sorted_groups.sort(key=lambda item: (_quality(item[1][0]), item[0]))
    headlines = [{"theme": name, "opportunity_id": items[0]["id"],
                  "title": items[0]["title"], "other_cards_in_theme": len(items)-1,
                  "reviewed": bool(items[0].get("critic_reviewed") and items[0].get("judge_reviewed")),
                  "status": items[0].get("status")}
                 for name, items in sorted_groups[:max_headlines]]
    themes = [{"theme": name, "count": len(items),
               "reviewed_count": sum(bool(c.get("critic_reviewed") and c.get("judge_reviewed")) for c in items),
               "representative_id": items[0]["id"],
               "all_opportunity_ids": [c["id"] for c in items]}
              for name, items in sorted(groups.items(), key=lambda x: (-len(x[1]), x[0]))
              for items in [sorted(items, key=_quality)]]
    return {
        "schema_version": 1,
        "generated_at": library.get("generated_at"),
        "source": "DERIVED_FROM_CANONICAL_SCOUT_LIBRARY",
        "purpose": "Editorial diversity and review focus, NOT duplicate identity or economic qualification",
        "total_original_cards": len(cards),
        "theme_count": len(groups),
        "headline_count": len(headlines),
        "headline_candidates": headlines,
        "themes": themes,
        "high_concentration": [
            {"theme": row["theme"], "cards": row["count"],
             "share": round(row["count"] / len(cards), 3)}
            for row in themes if len(cards) and row["count"] >= 5
            and row["count"] / len(cards) >= .2
        ],
        "buyers_verified": False,
        "commercial_execution_authorized": False,
        "warning": "Shared themes may include genuinely distinct opportunities. Do not auto-delete, auto-reject, infer novelty, or infer buyers.",
    }


def render_markdown(report: dict) -> str:
    lines = ["# Scout HQ — diversified research focus", "",
             "**Editorial theme grouping only; original opportunity records and gates are unchanged.**", "",
             f"Canonical active cards: {report['total_original_cards']} | themes: {report['theme_count']} | headline cards: {report['headline_count']}", "",
             "## Saturated research themes", ""]
    for row in report["high_concentration"]:
        lines.append(f"- {row['theme']}: {row['cards']} cards ({row['share']:.1%})")
    if not report["high_concentration"]:
        lines.append("No theme exceeds the concentration threshold.")
    lines += ["", "## One headline per theme", ""]
    for c in report["headline_candidates"]:
        title = " ".join(str(c["title"]).split()).replace("<", "‹").replace(">", "›").replace("|", "¦")[:180]
        lines.append(f"- **{title}** — {c['theme']}; +{c['other_cards_in_theme']} same-theme research cards; "
                     f"reviewed={str(c['reviewed']).lower()} (not a validated buyer)")
    return "\n".join(lines).rstrip() + "\n"


def write_focus(root: Path, library: dict | None = None) -> dict:
    if library is None:
        library = json.loads((root / "reports" / "library.json").read_text(encoding="utf-8"))
    report = build_focus(library)
    out = root / "reports"
    atomic_write(out / "focus.json", json.dumps(report, ensure_ascii=False, sort_keys=True,
                                                 indent=2, allow_nan=False) + "\n")
    atomic_write(out / "focus.md", render_markdown(report))
    return {"themes": report["theme_count"], "headlines": report["headline_count"],
            "concentration_alerts": len(report["high_concentration"]),
            "files": ["reports/focus.json", "reports/focus.md"]}
