# Gemini 2.5 Flash as the single shared model (free tier)

All three pipelines (P1/P2/P3) run on **Gemini 2.5 Flash** via the Google AI Studio free tier — byte-for-byte the same model, per [[0001-three-isolated-pipelines]]. This deliberately deviates from the video reference, which used Claude Opus 4.6 across three sub-agents.

**Why:** the organizers score *relative lift + architecture + token efficiency*, not raw model power ("a cheaper model with a better architecture can beat an expensive model with a lazy pipeline"). Gemini Flash is free, has excellent native function-calling (needed for the MCP tool loop), a 1M-token context (comfortably holds serialized subgraphs for GraphRAG), and strong reasoning. A single model held constant is the only way the P1→P2→P3 comparison is fair.

**Constraint not visible in code:** the free tier has RPM/RPD caps. Running 20 cases × 3 pipelines — with P3 doing many tool iterations each — can hit those limits, so the benchmark run needs throttling/backoff and possibly batching. Current free-tier quotas must be re-verified before the full run; a cheap paid key (or a small credit) is the fallback if throttling makes the run impractical. The model client stays behind a thin abstraction so swapping is a config change, not a rewrite.

