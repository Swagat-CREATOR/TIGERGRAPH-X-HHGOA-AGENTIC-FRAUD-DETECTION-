# Multi-provider fallback; the shared model is qwen/qwen3.8-max:free

**Supersedes the model choice in [[0002-gemini-flash-shared-model]]** (the fairness principle in 0002 still holds).

All three pipelines run on **one** model, `qwen/qwen3.8-max:free`, served through the **xkiro** OpenAI-compatible gateway. This replaces the planned Gemini 2.5 Flash — not by design, but because every free tier we had was exhausted during the benchmark runs.

**What happened.** The full workload is large: 20 exam cases × 3 pipelines (P3 alone is ~987K tokens) plus a held-out ablation of up to 30×3 (~1.84M tokens). Free-tier caps fell in sequence:
- **Gemini** (AI Studio free tier) — 20 requests/day; exhausted first.
- **Groq** (`openai/gpt-oss-120b`) — 200K tokens/day; exhausted next.
- **xkiro** aggregator — free models only (paid models return 403); settled on `qwen/qwen3.8-max:free`. The first key was rate-capped after ~1.3M tokens, so the resumable eval was split across additional 500K-token keys.

**Why it stays fair.** ADR-0002's core requirement is that **a single model is held byte-for-byte constant across P1/P2/P3** — that is the only way the lift is attributable to architecture rather than model power. That requirement is preserved: whichever provider serves the run, all three pipelines call the *same* model within that run. `src/llm.py` keeps every provider behind one interface (`make_llm()` routes on `LLM_PROVIDER`; `GroqLLM` was generalized with `base_url` + `key_env` so xkiro reuses it), and each client reads its key once at construction — so a run is internally consistent and `.env` can be re-pointed between slices without disturbing an in-flight process.

**Consequences.**
- The held-out `uncertain`-heavy behaviour (and the resulting `fraudF1 = 0` metric artifact) is partly a property of this model's conservatism under a weak trigger; a stronger model would likely commit more verdicts. The *architecture* lift (P1 blind → P2/P3 sighted) is model-independent and is what the submission claims.
- Reproduction requires only a valid key for any one supported provider; the model label is recorded in every run's `summary.json` / trace sidecar for provenance.

**Alternatives rejected.** A small paid key would have removed the quota juggling, but the free-tier-only constraint was a deliberate part of the "cheap model + good architecture" story, and the resumable split made the free tiers sufficient for a representative result.

