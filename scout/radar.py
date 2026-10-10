"""Scout V1 public-source radar: source-backed LEADS, not economic survivors.

Reuses established public APIs and RSS, Python's stdlib, and existing Scout
atomic reporting. No model, secrets, purchase, social login, or paid requests.
All source text is untrusted, all endpoints fixed by code, and all data
retrieval is bounded. Never call this a real customer or opportunity sale.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .state import atomic_write
from .boundary import url_key

MAX_BYTES = 1_500_000
MAX_ITEMS_PER_FEED = 32
MAX_LEADS = 1800
RETENTION_DAYS = 45
DEFAULT_TIMEOUT = 12

# High-volume discovery includes adjacent technologies, emerging products,
# distributed software and agricultural/electrical automation.
FEEDS = (
    ("hn_robotics", "hacker_news", "robot", "robotics", "innovation_adoption", 25),
    ("hn_farming", "hacker_news", "farm", "agriculture", "geographic_transfer", 25),
    ("hn_energy", "hacker_news", "energy", "energy", "technology_cost_curve", 25),
    ("hn_commerce", "hacker_news", "ecommerce", "commerce", "market_entry", 25),
    ("hn_ai", "hacker_news", "AI agent", "ai", "innovation_adoption", 25),
    ("hn_nfc", "hacker_news", "NFC", "commerce", "geographic_transfer", 25),
    ("github_robotics", "github", "robotics", "robotics", "open_source_leverage", 25),
    ("github_agriculture", "github", "smart-farming", "agriculture", "geographic_transfer", 25),
    ("github_ai", "github", "agents", "ai", "open_source_leverage", 25),
    ("github_energy", "github", "energy", "energy", "open_source_leverage", 25),
    ("arxiv_robotics", "arxiv", "cs.RO", "robotics", "innovation_adoption", 32),
    ("arxiv_ai", "arxiv", "cs.AI", "ai", "innovation_adoption", 32),
    ("arxiv_energy", "arxiv", "physics.app-ph", "energy", "innovation_adoption", 32),
    ("crossref_agriculture", "crossref", "precision agriculture", "agriculture", "innovation_adoption", 25),
    ("crossref_energy", "crossref", "battery storage", "energy", "technology_cost_curve", 25),
    ("huggingface_models", "huggingface", "", "ai", "open_source_leverage", 25),
    ("producthunt_launches", "producthunt", "", "commerce", "product_launch", 32),
    ("chile_nfc_commerce_news", "google_news", "NFC negocios Chile", "commerce", "geographic_transfer", 25),
    ("chile_vertical_farming_news", "google_news", "agricultura vertical Chile", "agriculture", "geographic_transfer", 25),
    ("chile_robotics_news", "google_news", "robotica agricultores Chile", "robotics", "geographic_transfer", 25),
    ("chile_energy_news", "google_news", "almacenamiento baterias solar Chile", "energy", "geographic_transfer", 25),
    ("global_robotic_farming_news", "google_news", "robotic farming startup", "robotics", "innovation_adoption", 25),
    ("chile_online_retail_news", "google_news", "ecommerce productos tiendas Chile", "commerce", "market_entry", 25),
)

# Economic routes are hypotheses to verify, never claimed as existing niches.
ROUTES = {
    "robotics": ("Chile import/distribution or local integration", "Check installed base, Chilean competitors, supplier pricing, certification and actual buyer budgets."),
    "agriculture": ("Chile-specific farm productivity or equipment distribution", "Interview farming operators; test operating savings against crop economics, climate and financing."),
    "energy": ("Energy hardware, efficiency, financing or infrastructure", "Check Chilean regulation, grid rules, procurement, installed cost and verified payback."),
    "commerce": ("Under-served product niche or differentiated incumbent alternative", "Verify demand and seller saturation with legally accessible marketplace data and supplier quotes."),
    "ai": ("Agent-enabled digital asset or localised specialised product", "Identify measurable customer job, willing buyer, existing competitors and unit economics."),
    "general": ("Potential technology adoption or market-entry hypothesis", "Identify a concrete payer, existing alternatives and a low-cost falsification test."),
}


# Topic classification must be grounded in visible title/description, not a
# provider's full-text search hit. Relevance is not business-quality evidence.
RELEVANCE_WORDS = {
    "robotics": ("robot", "robotic", "robótica", "robotica", "actuator", "mechatron",
                 "cobot", "manipulator", "autonomous mobile", "drones", "robot-arm"),
    "agriculture": ("farm", "farming", "agricultur", "crop", "irrigat", "soil", "hydropon",
                    "greenhouse", "livestock", "vertical farm", "agronom", "harvest",
                    "agricola", "agrícola", "cultivo", "invernadero", "riego"),
    "energy": ("energy", "battery", "solar", "power grid", "electricity", "storage",
               "photovoltaic", "thermal", "hydrogen", "grid", "microgrid", "superconduct",
               "electrochem", "heat pump", "electroly", "energía", "energia",
               "batería", "bateria", "electricidad", "almacenamiento"),
    "commerce": ("nfc", "ecommerce", "e-commerce", "retail", "merchant", "storefront",
                 "online shop", "shopify", "point of sale", "payment terminal", "contactless",
                 "vending", "product discovery", "dropship", "consumer product", "social commerce",
                 "comercio", "tienda", "tarjeta", "producto", "sin contacto", "compra"),
    "ai": ("llm", "language model", "ai agent", "agentic", "artificial intelligence",
           "machine learning", "transformer", "inference", "vision model", "neural",
           "model weights", "foundation model", "diffusion", "generative ai", "ai model"),
}

DISALLOWED_TERMS = ("crypto drainer", "wallet drainer", "credential stealer",
                    "phishing kit", "malware builder")


def _relevance_score(category: str, title: str, summary: str = "") -> int:
    source = (str(title) + " " + str(summary)).casefold()
    if any(banned in source for banned in DISALLOWED_TERMS):
        return 0
    patterns = RELEVANCE_WORDS.get(category, ())
    hits = sum(bool(re.search(r"(?<![a-z])" + re.escape(word) + r"[a-z]*(?![a-z])", source))
               for word in patterns)
    return min(5, hits)


def select_hints(root: Path, lenses: list[dict], *, max_items: int = 9,
                 max_chars: int = 2600) -> list[dict]:
    """Cheap, diverse, untrusted public leads as optional *search hints*.

    Only the Responses provider's independent search-source set may ground an
    opportunity. Never inject this file's URLs into trusted provenance.
    """
    file = root/"reports"/"radar.json"
    if not file.exists():
        return []
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            return []
        candidates = data.get("leads", [])
        if not isinstance(candidates, list):
            return []
    except (OSError, ValueError, TypeError):
        return []
    wanted = set()
    names = " ".join(x.get("id", "") for x in lenses if isinstance(x, dict))
    for keyword, category in (
        ("robot", "robotics"), ("farm", "agriculture"),
        ("agricultur", "agriculture"), ("energy", "energy"),
        ("seller", "commerce"), ("commerce", "commerce"), ("nfc", "commerce"),
        ("product", "commerce"), ("ai_", "ai"), ("adoption", "ai")):
        if keyword in names:
            wanted.add(category)
    # Do not starve broad investment or wildcard lenses of novel technologies.
    if not wanted:
        wanted = set(RELEVANCE_WORDS)
    picked, seen_categories = [], set()
    ranked = sorted((x for x in candidates if isinstance(x, dict)
                     and x.get("category") in wanted
                     and _relevance_score(x.get("category"), x.get("title",""), x.get("summary",""))),
                    key=lambda x: (x.get("quality_signal_score",0), x.get("first_seen","")),
                    reverse=True)
    for phase in (True, False):
        for x in ranked:
            if len(picked) >= max_items:
                break
            if phase and x["category"] in seen_categories:
                continue
            if any(y["public_url"] == x.get("url") for y in picked):
                continue
            candidate = {"category": x["category"], "headline": _clean(x["title"], 120),
                         "public_url": x["url"], "source": x["source"],
                         "research_status": "UNVERIFIED_SIGNAL"}
            if len(json.dumps(picked+[candidate],ensure_ascii=False)) > max_chars:
                break
            picked.append(candidate)
            seen_categories.add(x["category"])
    return picked


def _clean(value: Any, size: int = 380) -> str:
    value = str(value) if value is not None else ""
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", value).split())[:size]


def _date(value: Any) -> str:
    if not value:
        return ""
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        s = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(str(value))
        return dt.astimezone(timezone.utc).isoformat() if dt.tzinfo else ""
    except (ValueError, TypeError, OverflowError, OSError):
        return ""


def _url(url: str) -> str:
    # Never accept executable, local, relative, or synthetic URLs as evidence.
    return url_key(url)


def _fetch(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("HTTPS_ONLY")
    req = urllib.request.Request(
        url, headers={"User-Agent": "ScoutV1-OpenResearch/1.0 (public-data only)",
                      "Accept": "application/json, application/rss+xml;q=0.8, application/xml;q=0.5"})
    with urllib.request.urlopen(req, timeout=timeout) as stream:
        length = stream.headers.get("Content-Length")
        if length and int(length) > MAX_BYTES:
            raise ValueError("FEED_TOO_LARGE")
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("FEED_TOO_LARGE")
    return data


def _json(url: str, fetch=_fetch) -> dict | list:
    # Do not interpret arbitrary provider text as JSON under API failure.
    raw = fetch(url)
    return json.loads(raw.decode("utf-8"))


def _parse_hn(raw: dict | list, limit: int) -> list[dict]:
    if not isinstance(raw, dict):
        return []
    return [{
        "title": item.get("title", ""),
        "url": item.get("url") or ("https://news.ycombinator.com/item?id=" + str(item.get("objectID", ""))),
        "published_at": _date(item.get("created_at")),
        "signal_metric": {"hn_points": item.get("points"), "hn_comments": item.get("num_comments")},
    } for item in raw.get("hits", [])[:limit] if isinstance(item, dict) and item.get("title")]


def _parse_github(raw: dict | list, limit: int) -> list[dict]:
    if not isinstance(raw, dict):
        return []
    return [{
        "title": item.get("full_name") or item.get("name", ""),
        "url": item.get("html_url", ""),
        "published_at": _date(item.get("created_at")),
        "signal_metric": {"github_stars": item.get("stargazers_count"),
                          "github_forks": item.get("forks_count")},
        "summary": item.get("description", ""),
    } for item in raw.get("items", [])[:limit] if isinstance(item, dict)]


def _parse_crossref(raw: dict | list, limit: int) -> list[dict]:
    rows = raw.get("message", {}).get("items", []) if isinstance(raw, dict) else []
    out = []
    for item in rows[:limit]:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        title = title[0] if isinstance(title, list) and title else ""
        out.append({"title": title, "url": item.get("URL", ""),
                    "published_at": _date(item.get("created", {}).get("date-time")),
                    "signal_metric": {"crossref_citations": item.get("is-referenced-by-count")}})
    return out


def _parse_huggingface(raw: dict | list, limit: int) -> list[dict]:
    if not isinstance(raw, list):
        return []
    return [{
        "title": item.get("id", ""), "url": "https://huggingface.co/" + str(item.get("id", "")),
        "published_at": _date(item.get("createdAt") or item.get("lastModified")),
        "signal_metric": {"hf_downloads": item.get("downloads"), "hf_likes": item.get("likes")},
    } for item in raw[:limit] if isinstance(item, dict) and item.get("id")]


def _parse_producthunt(raw: bytes, limit: int) -> list[dict]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("ATOM_EXTERNAL_ENTITIES_REJECTED")
    root = ET.fromstring(raw)
    atom = "{http://www.w3.org/2005/Atom}"
    result = []
    for entry in root.findall(atom + "entry")[:limit]:
        link = next((x.attrib.get("href", "") for x in entry.findall(atom+"link")
                     if x.attrib.get("rel") == "alternate"), "")
        body = entry.findtext(atom+"content") or ""
        result.append({"title": entry.findtext(atom+"title") or "",
                       "url": link, "published_at": _date(entry.findtext(atom+"published")),
                       "summary": re.sub(r"<[^>]+>", " ", body),
                       "signal_metric": {}})
    return result


def _parse_arxiv(raw: bytes, limit: int) -> list[dict]:
    # Bounded parser against public RSS. Never load DTD/external entities.
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("RSS_EXTERNAL_ENTITIES_REJECTED")
    root = ET.fromstring(raw)
    result = []
    for entry in root.findall(".//item")[:limit]:
        title = entry.findtext("title") or ""
        result.append({
            "title": title, "url": entry.findtext("link") or "",
            "published_at": _date(entry.findtext("pubDate")), "signal_metric": {},
            "summary": entry.findtext("description") or "",
        })
    return result


def feed_url(kind: str, query: str, *, now: datetime, limit: int) -> str:
    # Immutable curated endpoints, never derived from external feed response.
    if kind == "hacker_news":
        return ("https://hn.algolia.com/api/v1/search_by_date?" +
                urllib.parse.urlencode({"query": query, "tags": "story",
                                        "hitsPerPage": limit,
                                        "numericFilters": f"created_at_i>{int((now-timedelta(days=2)).timestamp())}"}))
    if kind == "github":
        return ("https://api.github.com/search/repositories?" +
                urllib.parse.urlencode({"q": f"{query} created:>{(now-timedelta(days=14)).date().isoformat()}",
                                        "sort": "updated", "order": "desc", "per_page": limit}))
    if kind == "arxiv":
        return "https://export.arxiv.org/rss/" + query
    if kind == "crossref":
        return ("https://api.crossref.org/works?" +
                urllib.parse.urlencode({"query.title": query, "rows": limit,
                                        "filter": f"from-created-date:{(now-timedelta(days=2)).date().isoformat()}",
                                        "select": "DOI,title,URL,created,is-referenced-by-count"}))
    if kind == "huggingface":
        return "https://huggingface.co/api/models?" + urllib.parse.urlencode(
            {"sort": "trendingScore", "direction": "-1", "limit": limit})
    if kind == "producthunt":
        return "https://www.producthunt.com/feed"
    if kind == "google_news":
        return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": query, "hl": "es-419" if "Chile" in query else "en-US",
             "gl": "CL" if "Chile" in query else "US",
             "ceid": "CL:es-419" if "Chile" in query else "US:en"})
    raise ValueError("UNSUPPORTED_FEED")


def scan_feed(spec: tuple, *, now: datetime, fetch=_fetch) -> list[dict]:
    feed_id, kind, query, category, route, limit = spec
    url = feed_url(kind, query, now=now, limit=limit)
    if kind in ("arxiv", "google_news"):
        entries = _parse_arxiv(fetch(url), limit)
    elif kind == "producthunt":
        entries = _parse_producthunt(fetch(url), limit)
    else:
        payload = _json(url, fetch)
        parser = {"hacker_news": _parse_hn, "github": _parse_github,
                  "crossref": _parse_crossref, "huggingface": _parse_huggingface}[kind]
        entries = parser(payload, limit)
    result = []
    for item in entries[:MAX_ITEMS_PER_FEED]:
        canonical = _url(str(item.get("url", "")))
        title = _clean(item.get("title", ""), 180)
        if not title or not canonical:
            continue
        summary = _clean(item.get("summary", ""), 350)
        relevance = _relevance_score(category, title, summary)
        if kind in ("huggingface", "producthunt") and relevance == 0:
            # This fixed endpoint lists actual model records, which themselves
            # establish AI topic membership but absolutely NOT buyer demand.
            relevance = 1
        if relevance == 0:
            continue
        route_text, first_test = ROUTES.get(category, ROUTES["general"])
        published = item.get("published_at") or ""
        if published:
            try:
                published_dt = datetime.fromisoformat(published)
                if published_dt < now-timedelta(days=30) or published_dt > now+timedelta(days=1):
                    continue
            except ValueError:
                continue
        uid = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        result.append({
            "id": "rad_" + uid, "title": title, "url": canonical,
            "source": kind, "feed_id": feed_id, "category": category,
            "hypothesis_type": route, "first_seen": now.isoformat(),
            "published_at": published, "summary": summary,
            "quality_signal_score": relevance,
            "signal_metric": {k: v for k, v in item.get("signal_metric", {}).items()
                              if isinstance(v, int) and not isinstance(v, bool) and v >= 0},
            "possible_value_capture": route_text,
            "first_validation_test": first_test,
            "evidence_status": "PUBLIC_SOURCE_SIGNAL_NOT_VERIFIED_MARKET_DEMAND",
            "buyer_verified": False, "economics_verified": False,
            "investment_authorized": False, "survivor": False,
        })
    return result


def build_snapshot(existing: dict | None, incoming: list[dict], *,
                   now: datetime, errors: list[str]) -> dict:
    if now.tzinfo is None:
        raise ValueError("RADAR_REQUIRES_TIMEZONE")
    retained = {}
    cutoff = now-timedelta(days=RETENTION_DAYS)
    for item in (existing or {}).get("leads", []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        try:
            first = datetime.fromisoformat(item["first_seen"])
            if (first.tzinfo and first >= cutoff and _url(item.get("url", ""))
                    and _relevance_score(item.get("category",""), item.get("title",""),
                                         item.get("summary","")) > 0):
                retained[item["id"]] = item
        except (ValueError, TypeError, KeyError):
            continue
    new = 0
    for item in incoming:
        key = item["id"]
        if key not in retained:
            new += 1
            retained[key] = item
        else:
            # Immutable original source plus newest observed metadata; do not
            # let an unreviewed public signal change Scout's economic status.
            old = retained[key]
            old["signal_metric"] = item["signal_metric"]
            old["quality_signal_score"] = item["quality_signal_score"]
            old["last_observed_at"] = now.isoformat()
    leads = sorted(retained.values(),
                   key=lambda x: (x.get("quality_signal_score", 0),
                                  x["first_seen"], x["id"]), reverse=True)[:MAX_LEADS]
    return {
        "schema_version": 1, "generated_at": now.astimezone(timezone.utc).isoformat(),
        "source_type": "UNREVIEWED_PUBLIC_SOURCE_SIGNALS",
        "spending_usd": 0, "model_calls": 0,
        "current_rolling_leads": len(leads), "new_signals_this_cycle": new,
        "fetch_degraded": bool(errors), "failed_feeds": errors,
        "counts_by_category": dict(Counter(x["category"] for x in leads)),
        "leads": leads,
        "disclaimer": "A public signal is not an opportunity, buyer, prediction, recommendation or survivor. This collection is no substitute for independent economic validation.",
    }


def render_markdown(snapshot: dict) -> str:
    lines = [
        "# Scout V1 — Public-source opportunity radar", "",
        "Generated: " + snapshot["generated_at"], "",
        "**Unreviewed technology/market signals, NOT verified businesses or investments.**", "",
        f"- Rolling leads: {snapshot['current_rolling_leads']}",
        f"- New this cycle: {snapshot['new_signals_this_cycle']}",
        "- API/model spending: $0.00; sales and invested capital: none",
        "- Feed failures (fail-open for public intake only): " + (", ".join(snapshot["failed_feeds"]) or "none"),
        "- Categories: " + ", ".join(f"{k} {v}" for k, v in sorted(snapshot["counts_by_category"].items())),
        "", "## Recently encountered signals", "",
    ]
    for x in snapshot["leads"][:75]:
        title = (_clean(x["title"]).replace("<", "‹").replace(">", "›")
                 .replace("[", "⟦").replace("]", "⟧"))
        lines.extend([
            "### " + title,
            "- Source: " + x["url"],
            "- Domain: " + x["category"] + " | Suggested angle: " + x["possible_value_capture"],
            "- First test: " + x["first_validation_test"],
            "- Status: **unverified research lead**", "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def run_radar(root: Path, *, now: datetime | None = None, fetch=_fetch,
              feeds: tuple = FEEDS) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("RADAR_REQUIRES_TIMEZONE")
    path = root/"reports"/"radar.json"
    existing = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict) or existing.get("schema_version") != 1:
                raise ValueError("INVALID_EXISTING_RADAR")
        except (ValueError, UnicodeError):
            # Never destroy previous history if an on-disk radar snapshot is damaged.
            raise ValueError("CORRUPT_RADAR_CACHE") from None
    arrivals, errors = [], []
    for spec in feeds:
        try:
            arrivals.extend(scan_feed(spec, now=now, fetch=fetch))
        except (urllib.error.URLError, TimeoutError, ValueError, ET.ParseError,
                KeyError, TypeError, UnicodeError, json.JSONDecodeError):
            # Do not persist source text or provider error strings.
            errors.append(spec[0] + ":unavailable_or_invalid")
    # If every feed failed, do not rewrite a valid cache with a misleading refresh.
    if not arrivals and len(errors) == len(feeds):
        raise RuntimeError("ALL_PUBLIC_FEEDS_UNAVAILABLE")
    snap = build_snapshot(existing, arrivals, now=now, errors=errors)
    atomic_write(path, json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)+"\n")
    atomic_write(root/"reports"/"radar.md", render_markdown(snap))
    return {k: v for k, v in snap.items() if k not in ("leads", "disclaimer")}
