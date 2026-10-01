# AGENTS.md — Scout V0

Scout is an evidence-first opportunity intelligence system, not an execution engine.

Rules for coding agents:
1. Keep V0 small. Prefer deleting complexity over adding architecture.
2. No OpenAI Agents API, custom agent framework, GUI, vector DB, or autonomous economic execution.
3. Preserve the Opportunity Record and the core/vertical boundary.
4. Discovery and adversarial criticism must remain logically separate.
5. Fatal gates are conjunctive; never weaken them just to increase survivor count.
6. Python decides deterministic thresholds, budgets, dedupe and state transitions.
7. AI runtime must remain behind `AIClient`.
8. Never commit secrets. `OPENAI_API_KEY` is read from environment/GitHub Actions secrets only.
9. Every paid AI call must be metered best-effort. Budget exhaustion must stop safely, not partially corrupt state.
10. Rejections are useful output. Never patch an opportunity until it survives.
11. Do not change V0 permissions to trade, buy, contact third parties, or deploy businesses.
12. Tests should focus on state, gates, dedupe, budget, parsing and calibration behavior—not infrastructure theatre.
