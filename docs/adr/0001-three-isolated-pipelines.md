# Three isolated pipeline implementations for a defensible benchmark

Our headline result is the *relative lift* from Plain RAG (P1) → GraphRAG (P2) → Agentic GraphRAG (P3) on one shared model. We implement the three as **separate code paths** that share only a common model client, data/retrieval layer, and evaluation harness — rather than a single agent with capability flags that disable graph/tools to emulate the baselines.

**Why:** capability-flag emulation is cheaper to build but confounded — a skeptical judge (or reviewer) can argue the baselines were deliberately hobbled, which would undermine the one number we most want believed. Separate paths make each pipeline a faithful, standalone implementation of its category, so the comparison is honest and hard to attack.

**Consequences:** more code and some duplication across the three entrypoints; we mitigate by factoring the shared model/data/eval concerns into a common library so only the *retrieval + control flow* differ per pipeline. Reversing this later (collapsing to one parameterized path) would mean re-validating that the comparison is still fair.

Considered and rejected: **(B) one agent with capability flags** — less code, but not defensible as a benchmark.

