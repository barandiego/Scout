# Scout V1 — research brain routing and credit activation

## Current state: staged and disabled, no trial spending

Scout V1 public radar and the original $0.50/day Scout V0 research continue operating.
This PR **prepares** a different OpenAI model profile and admission envelope; it does
not enable those paid models or increase the live limit.

## Exactly which model performs which task

| Task | Role | Model | Reasoning | Active in funded trial? |
| --- | --- | --- | --- | --- |
| 4-hour public radar (23 feeds) | Intake | none | deterministic | Yes, free |
| URL/topic dedupe and initial priority | Screening | none | deterministic | Yes, free |
| Optional model-based micro-triage | Cheap triage | `gpt-6-luna` | medium | **No; not implemented** |
| Independent web-based business discovery | Discovery | `gpt-6.1-sol` | medium | Yes |
| Scrutinise competitors, differentiation, supply/demand, risks, economics | Critic | `gpt-6.1-sol` | high | Yes |
| Specialist commercial rubric, HQ-worthiness, falsification | Judge | `gpt-6.1-sol` | medium | Yes |
| Exceptional heavyweight investment/innovation investigation | Deep adversary | `gpt-6-astra` | high | **No; not implemented** |

Using Sol for the final judge rather than Astra in every 4-hour cycle protects
the economics of the experiment. A stronger judge is worthless if too much of
the budget goes toward repeatedly analysing weak ideas. Astra should only
be introduced when comparison results demonstrate a real incremental advantage.

Official reference: https://developers.openai.com/api/docs/models
And API pricing: https://developers.openai.com/api/docs/pricing

The correct model IDs have been checked in the official catalogue. Access
for **the specific authorised Scout API project** remains unverified until
a no-inference model-list preflight runs using that project's credential.

## Seven-day research trial constraints

The staged `config/research_trial.yaml` uses:

- **US$15.00 estimated total maximum across *all* Scout AI calls in window**,
  including the original V0 scheduled cycles.
- **US$3.00 estimated UTC-day maximum**; original V0 calls count.
- **US$1.20 estimated per-cycle maximum**, with conservatively bounded
  pre-call reserves: discovery $0.60, critic $0.60, judge $0.40.
- One critic and one judge per cycle, at most four web calls per search
  stage, bounded outputs, bounded candidate batch and retained V1 review queue.
- Stage-level Sol model/effort routing is selected only in the trial;
  otherwise existing gpt-5.6-luna/gpt-5.6-terra routing remains unchanged.

Both activation conditions are required:

1. An authorised config change sets `enabled: true` and explicit UTC
   `starts_at_utc` / `ends_at_utc` spanning at most seven days.
2. The GitHub Actions repository variable `SCOUT_RESEARCH_TRIAL_ARMED` is
   explicitly set to `1` after the Scout API project balance, models,
   current pricing and billing setting are verified.

When both are armed, the existing four-hour `cycle` schedule automatically
uses the trial Sol profile. It automatically reverts to the baseline profile
when the window expires or the environment flag is absent. The radar schedule
continues free. The same protected journal serialises and counts baseline and
trial calls within the trial window. Any ambiguous/missing usage or unresolved
pending stage stops further paid attempts.

The stage reserves and recorded usage estimates provide **conservative
admission control, NOT a guaranteed provider-side hard billing cutoff**:
a model can return more billable tokens than anticipated, and an interrupted
transport may conceal charges. Provider-side project monthly spending budgets
are **soft alerts**, not strict limits. Do not assume buying just $15 of
credit mathematically eliminates the chance of overage.

## What to do *after* adding Scout credits

1. Visit https://platform.openai.com/ and select the **same API
   organisation/project** currently used by the Scout GitHub Action.
2. Under Billing, check the existing credit balance and purchase additional
   prepaid credit *only if desired*. Disable auto-recharge if avoiding
   automatic purchases. Keep funds separate from project budget alerts.
3. In Scout project Settings > Limits, set the monthly project **soft alert**
   sufficiently above already-used amount plus the trial envelope, and
   allow the intended models. Note the old $10 project alert is not a hard cap.
4. Check that the current GitHub `OPENAI_API_KEY` secret still belongs to
   the same authorised Scout API project. **Do not copy or paste keys into
   issues, PRs or ChatGPT.**
5. Dispatch Scout V0 > Run workflow > `trial-model-check` first.
   It checks authorised model IDs with the existing project key but **does not
   enable or invoke paid inference**.
6. In a separate approved activation change, set the time window and
   `enabled: true` and set the repository variable
   `SCOUT_RESEARCH_TRIAL_ARMED=1` only after credit/model checks succeed.
   Dispatch `trial-preflight` for the active profile. From then on,
   the normal recurring `cycle` automatically uses Sol until expiry.
7. Inspect `python -m scout.cli trial-status`, persisted runs and user-visible
   library for budget remaining and real research outcomes. Remove the
   activation variable immediately for an emergency pause.

No cron schedule, key, billing setting, platform credit, marketplace action,
advertising purchase or investment is changed in this staged PR.

## Key acceptance criteria

A better Scout finds independently sourced, plausible, low-owner-hour, specific
market opportunities with a buyer/path to revenue and realistic Chile adaptation.
Measure by real HQ-worthy research survivors and bounded real-world validation
tests, not raw source-hit counts or promises of NVIDIA/Bitcoin-scale returns.
Records are not authorised to execute trades or spend economic capital.
