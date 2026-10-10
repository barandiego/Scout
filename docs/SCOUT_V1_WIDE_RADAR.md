# Scout V1: Broad discovery, research backlog, economic innovation

**Objective.** Find evidence-backed, transferable opportunities for Diego's
portfolio in Chile and worldwide: incumbent positioning, e-commerce niches,
foreign-to-Chile localisation, NFC commerce, agricultural robotics, energy,
public markets, early-adoption technologies, and asymmetric investing.
Consider short/medium/long time horizons, small or large capital envelopes,
and automation/digital-asset leverage.

## Build vs proven public infrastructure

Preserve the existing Scout Pydantic core, Responses research adapter, GitHub
Actions, durable cost journal, critic, judge and public procurement vertical.
**Reuse** public-source APIs rather than constructing a private crawler/search
engine or migrating Scout to Forge: Hacker News Algolia, GitHub Search, arXiv,
Crossref, Hugging Face models, Product Hunt Atom, and Google News RSS including
Chile-focused searches. No social login or unauthorized scraping.

## How it operates

1. **Public radar**: scout/radar.py queries 23 curated feeds on a separate
   GitHub Actions schedule every 4h. Its input/output are bounded, URLs
   canonicalized and headline/topic relevance filtered. Each source-backed
   lead is explicitly UNREVIEWED, with a possible business route and
   first validation question. The rolling cache caps at 1,800 signals.
   Outputs: reports/radar.json and reports/radar.md. No model call,
   commercial side effect, market trade or API key. GitHub Actions minutes
   and public endpoint uptime still apply.
2. **Independent research**: the existing governed Scout cycle receives at
   most nine *untrusted radar hints*. Only its own Responses tool-returned
   web search sources may validate provenance. Hints never supply trust.
3. **Durable review queue**: previously, research-qualified discoveries
   beyond the one-per-cycle paid reviewer limit were dropped. Now they
   are saved as WATCH/deferred_by_review_cap and reviewed in subsequent
   cycles when budgets allow. Material updates remain subject to existing
   dedupe. Critic vetoes and hard economic/source gates are not weakened.
4. **Specialist economic lenses**: eight rubrics examine tangible seller
   scarcity vs real demand, landed margins, defensible incumbent wedges,
   innovation adoption lag, Chilean licensing, robotics operations,
   energy project economics and downside-aware asset/investment theses.
   Original general/open-finance/geographic/public-market rubrics stay.
5. **Innovation research playbooks**: scout/innovation.py builds research
   hypotheses for each WATCH/SURVIVED record. Questions include buyer,
   sales channel, source/competitor checks, project costs, alternatives,
   legal access, geographic transfer and first falsification experiment.
   Outputs: reports/innovation_backlog.json and .md. These are prompts for
   real validation, not fabricated business cases.

## Truth hierarchy

- PUBLIC_SIGNAL: source observed, no customer or economic proof.
- WATCH: unresolved/queued canonical candidate, not HQ-ready.
- SURVIVED: evidence-backed HQ research worthy, **not validated profit**.
- REAL_VALIDATION: separate buyer, unit-economics, counterparty/market test.
- CONFIRMED_REVENUE: actual third-party receipts after accounting.

The last two stages are NOT automatically assigned by V1. No invention of
buying intent, Chilean marketplace scarcity, 10x investment returns,
supplier arrangements, or regulatory rights.

## Cost and model strategy

The **existing** GitHub Scout paid schedule remains at its original
US$0.08/cycle and US$0.50/day and continues using its original models;
new public radar adds no paid inference. Its discoveries now use untrusted
public radar hints, and its judge sees alternative positioning hypotheses.

The proposed smarter paid comparison (GPT-6 Luna discovery, GPT-6.1 Sol
research/critic, selective GPT-6 Astra deep evaluation) is intentionally
**not activated by this infrastructure patch**. Prior proposal: US$15
cumulative over seven days, at most US$3 in any day. Before activating,
implement/test an exact seven-day model/tool cost ledger, account/model
preflight, source-timeout and spend-stop checks, plus separate external
account budget guard. Estimated runtime metering is not a bank guarantee.

Evaluate this pipeline against V0 on comparable tasks and a prospective
human-rated shortlist. Benchmark historical NVIDIA/Bitcoin only using
information published by the chosen historical date; retrospective
success cannot guarantee predictive profitable investing.

## Verification

```bash
pip install -e '.[dev]'
python -m scout.cli validate
python -m scout.cli calibrate
pytest -q
python -m scout.cli radar       # public network, no model calls
python -m scout.cli library     # pure local derived report
```

Full test suite/locking is Linux GitHub Actions-specific; Windows Python
lacks fcntl. CI does not use paid model calls. No trade, ads, products,
supplier outreach or live spending is authorised by this change.
