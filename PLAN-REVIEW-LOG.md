# Plan Review Log: Agentic Fraud Investigation on TigerGraph (HHGOA)

Act 1 (grill-with-docs) complete — plan locked in `PLAN.md`; `CONTEXT.md` reconciled to the dataset README's language; ADRs 0001–0004 recorded.

Act 2 (Codex adversarial review): running. `codex` 0.156.1 installed; MAX_ROUNDS=2. The read-only exec-helper cannot spawn on this Windows box, so Codex cannot read repo files itself — worked around by piping `PLAN.md` + `CONTEXT.md` + the four ADRs into Codex via **stdin** (Codex reasons over the `<stdin>` block, no file reads needed). Fresh thread each round-1; resume for round-2.

## Round 1 — Codex (thread 01a0d305-f49e-75b2-ae58-0b950dfc5103) — VERDICT: REVISE

Full critique (grouped). Note: Codex did **not** have the dataset README (authoritative for schema/policy/patterns/actions), so several findings are really "pin the README's contract into the build spec" rather than genuine unknowns.

**Contract / schema**
- Answer schema never defined in-plan; field list omits `pattern`, `verdict`, `fraud_probability`, `exposure`, `trigger`, `similar_prior_cases`, SAR null/status semantics. → commit a canonical schema with enums/required/null rules.
- Behaviour depends on an "unspecified" README/policy/R1–R10/§5/§6. → pin policy + schema + action-route matrix into the build spec.
- 14 NBA identifiers treated as examples; no action→approval mapping, no initial/final applicability. → lock the full enum + route + execution semantics.
- SAR predicate ("confirmed/strongly-suspected AND >$1,000, or shared link, or coordinated") is ambiguous. → encode the exact Boolean and emit triggering reasons.

**Benchmark validity (the Innovation headline)**
- Label leakage: closed-case narratives with outcomes/patterns left in the retrieval index leak answers for held-out eval cases. → split closed cases before indexing; strip outcome text; exclude target + near-dups.
- P3 writes `Case` vertices before P1/P2 → later pipelines/re-runs retrieve P3's own answers, breaking isolation. → per-pipeline namespaces/snapshots; exclude generated exam cases; deterministic IDs + idempotent upsert + current-case exclusion filter.
- "Same model" ≠ fair unless prompt/context/retry/token accounting are matched. → matched I/O schemas, token categories, latency boundaries, per-case budgets.
- Lift metric only scores pattern+verdict, but deliverable is graded on probability/exposure/NBA/SAR/evidence/explainability too. → add semantic evaluators per scored dimension.
- Reduced-sample P1/P2 (5 cases) is incomparable to P3-on-20. → predeclare one common eval set for all three.
- `ClosedCase` labels (`confirmed_fraud`/`cleared`) ≠ verdicts (`fraud`/`legitimate`). → explicit normalization map; keep raw labels out of answers.
- Risk of conflating `risk_score` with `fraud_probability`; no calibration method despite "calibrated" claim. → name probability separately, validate range, calibrate or drop the claim.

**Graph model**
- Targeted closure can miss episode transactions on another card / outside Nov–Dec / beyond one hop → incomplete exposure & connected-card conclusions. → explicit time/hop bounds + an actually-implemented out-of-graph fallback.
- Dropping `V1–V339` conflicts with glossary's "V/C/D/M usable as signals." → retain approved subset or prove none needed.
- `CONNECTED_TO` underspecified (by device? email? region?); no first/last-seen or supporting txns. → typed attributed edges with provenance + temporal bounds.
- `Case` edges don't clearly link trigger/customer/evidence/SAR/NBA. → deterministic Case properties + edges for full auditability.

**Agent control / compliance**
- Stop rules not operationally bounded; agent can loop. → hard caps on iterations, tool calls, wall-time, tokens, repeated requests.
- Initial/final NBA underspecified: no evidence-request structure, response model, timeout, `what_changed` def. → typed request/response protocol + deterministic before/after diff.
- Exposure needs episode dedup by TransactionID; multi-signal paths can double-count. → identity-based episode construction, sum |amount| once.
- "Files a SAR" exceeds integrations & conflicts with routing. → produce SAR **draft** + `FILE_REPORT` recommendation; prohibit external filing.
- Schema validation alone accepts unsafe answers (SAR w/o reason, executed L2, unsupported claims, verdict on risk_score alone). → deterministic policy/compliance validator before emit + write-back.
- Domain drift: plan says "alerts", `customer_history` vs glossary's `Trigger`/`Case`/avoid-"history". → enforce glossary vocab in tool names/prompts/JSON/UI.
- Pattern logic not concretely implemented (windows/thresholds/channel tests for all 7 enums). → specify query windows/thresholds/evidence predicates.
- Tool-call observability too thin (counts only; no args/results/errors/provenance/model-version/snapshot/retries). → structured per-case trace + stable evidence refs.

**Ops / timeline**
- Direct-GSQL fallback not automatically equivalent to MCP (shapes/errors/auth/tracing differ). → build+test one adapter interface before P3.
- TigerGraph vector search / Savanna perms / embedding dims / Gemini+PydanticAI function-calling assumed, not smoke-tested. → first 30 min prove load→vector→model→structured-output→one tool loop.
- Free-tier quotas × up to 60 runs × tool loops × retries can eat the schedule; paid/Community fallback isn't instant. → hard call budgets + quota-tested 2-case pilot first.
- Hand-checking 2–3/20 can't establish policy correctness. → automated semantic checks on every case.
- Whole build (ingest+vector+adapter+agent+3 pipelines+eval+write-back+dashboard) in 6–7 h is unrealistic without scaffold. → commit P3 + schema/policy validation; freeze P1/P2 + UI as explicit optional cuts.

### Claude's response (final arbiter) — PLAN.md revised

Most findings are cheap methodology/wording pins that make the plan more defensible **without adding build hours** — two of them (smoke-test first, policy validator) actually *reduce* risk and rework. Accepted and folded into `PLAN.md`:

- **Step 0 (new, 0:00–0:30): end-to-end smoke test** — prove graph load → vector query → Gemini call → structured output → one tool loop, and build+test the single graph-client adapter interface so MCP↔direct-GSQL is a drop-in (kills the "fallback isn't free" and "assumed integrations" risks up front).
- **Schema freeze** in Step 3: the *full* README answer schema as Pydantic (trigger, case{pattern/verdict/fraud_probability/exposure/status}, sar nullable, next_best_actions{initial/final/what_changed}, evidence[], evidence_requests, similar_prior_cases, stop_reason, tokens/tool_calls/latency_s), plus the locked **14-action enum + auto/L1/L2 route matrix** and the SAR Boolean predicate — pinned from the README (authoritative; Codex lacked it).
- **Deterministic policy/compliance validator** (Step 3) run before every emit + write-back: SAR only with a qualifying reason; no auto-execution of L1/L2; verdict never on risk_score alone; every evidence claim carries entity_ids. Protects the 50% (accuracy+NBA) + 10% (explainability) directly.
- **Leak-free eval** (Step 6): split closed cases into memory-seed vs held-out **before** indexing; strip outcome text; exclude the target case + near-dups from retrieval; one **common eval set across P1/P2/P3**; score pattern + verdict + exposure + policy-compliance (not schema-only). Dropped the unbacked "calibrated" wording — `fraud_probability` is the agent's estimate, range-validated, calibration noted as out of scope.
- **Isolation/idempotency** (Step 4): exam `Case` write-backs live in a separate namespace excluded from P1/P2 + eval retrieval; deterministic Case IDs + idempotent upsert; similar-case retrieval filters the current case.
- **Agent loop caps** (Step 4): hard max iterations / tool-calls / wall-time / token-budget per case; stop rules §6 operationalized.
- **Quota pilot** (Step 5): 2-case quota-tested pilot + hard per-case call budgets before the full 20; automated semantic checks on all 20, hand-review 2–3 on top.
- **Wording**: Goal now says "cases/triggers" not "alerts"; SAR is **drafted** with a `FILE_REPORT` recommendation (never filed externally); exposure = sum of |amount| over the episode **deduped by TransactionID**; ClosedCase→verdict **normalization map** added.
- **Graph**: `CONNECTED_TO` now carries the shared-key type + value; `Case` links trigger-txn/card/customer with evidence/NBA/SAR stored as Case properties.

Deferred with reason (gold-plating for a 6–7 h build; logged, not silently dropped):
- **Full typed-attributed provenance edge model for everything** — use Case JSON properties + a few typed edges instead; full temporal-provenance graph is more than the scored dimensions need in the budget.
- **Retain a V-feature subset** — keep the ADR-0004 drop of `V1–V339`; C/D/M + named identity columns stay, and any single V feature is fetchable out-of-graph by `TransactionID` (per ADR-0004). Not worth the load time.
- **Prove closure completeness formally** — keep the targeted closure + explicit time/hop bounds + the out-of-graph fetch fallback (already ADR-0004); a completeness proof over 590k rows doesn't fit the budget and the 20 cases are the only scored targets.

Verdict stands as input to Round 2; revised `PLAN.md` handed back for re-review.

## Round 2 — Codex (fresh session; `resume` cannot receive stdin in this env) — VERDICT: REVISE

Re-review of the revised PLAN.md (+CONTEXT+ADRs via stdin). `codex exec resume` did not forward the piped stdin block, so Round 2 was run as a fresh skeptical session over the current artifacts — a stronger test than resume. Blockers:
- Schema is field-names-only, not frozen types/enums/null-rules/strictness/filename-binding/SAR-structure. → strict Pydantic/JSON Schema, `additionalProperties=false`.
- `pattern="undocumented"` is scored on a free-text description. → add required `pattern_detail`.
- Label isolation must also cover `ClosedCase` vertices/labels/notes + graph similar-case retrieval, not just the vector index. → held-out cases as unlabeled raw context only; block every label-bearing graph/memory path + near-dups.
- Neighbor closure bounded to Nov–Dec, but eval closed cases are Jul–Oct → their graph context wouldn't load. → time-local closures around every eval case.
- `request_evidence` is a P3-only channel; simulator could leak labels. → frozen label-blind simulator.
- Self-reported token/tool/latency ≠ fair accounting. → external harness counts every call/retry/tool token + wait.
- Exposure has no deterministic episode definition. → require `episode_transaction_ids`, dedup, deterministic anchor/window/link rules.
- `CONNECTED_TO` lacks temporal/provenance → lifelong-shared-key false links. → time-windowed joins + txn-level membership.
- V-features claimed fetchable but no tool exists. → add metered `transaction_features(TransactionID)`.
- Validator doesn't enforce every R1–R10 / 2-evidence stop / SAR precedence / routes / status transitions. → compile the complete policy with adversarial tests.
- Hard caps named but not numeric; no cap-exhaustion fallback. → exact limits + deterministic finalization with `stop_reason`.
- Scoring rubric incomplete (normalization, `uncertain`, exposure tolerance, weighting, lift formula). → freeze scoring/lift spec before any run.
- "calibrated" vs calibration-out-of-scope contradiction. → report uncalibrated.
- Timeline has no fixed eval-set size; ~2 h for 20 P3 + 3-pipeline eval + UI is tight. → cap eval N + per-case budget; cut/defer explicitly.
- Nice-to-haves: pin Gemini model ID/params/retry/eval-order; first-class graph relations for affected-txns/evidence.

### Claude's response (final arbiter) — PLAN.md revised again
Accepted and folded in (all cheap plan-level commitments or schema fields — no scope blow-up): `pattern_detail`; label-blindness across **both** vector and graph memory + near-dups; **time-local closures around every scored entity (exam Nov–Dec + eval Jul–Oct)**; frozen **label-blind** evidence simulator (with the explicit note that the request_evidence asymmetry is the measured agentic lift, not leakage); harness-side token metering wrapping every call/retry; `episode_transaction_ids` + deterministic deduped exposure; `CONNECTED_TO` time-window + supporting-txn refs; metered `transaction_features(TransactionID)`; validator compiling full R1–R10 + §6 two-evidence + SAR precedence + routes + status with adversarial tests; **concrete caps (≤8 iters / ≤20 tools / ≤90 s / ≤40k tok) + deterministic cap-hit finalization**; **frozen scoring/lift spec + fixed eval N=30 (→10 under pressure)**; `fraud_probability` reported uncalibrated; pinned model ID/params/retry/eval-order (Step 0).
Deferred with reason: full per-transaction provenance edge model + first-class evidence/affected-txn graph relations (Case properties + `episode_transaction_ids` suffice for the scored dimensions in-budget); in-graph V-subset (the `transaction_features` tool covers it).

### Resolution — round cap (MAX_ROUNDS=2) reached; substantively converged, formal verdict REVISE
Codex's residual REVISE is not a design disagreement: every substantive finding across both rounds is now in `PLAN.md`. What remains between the plan and Codex's bar is that Codex wants the **artifacts themselves** — the strict JSON Schema, the compiled R1–R10 validator + its test suite, and the frozen scoring formula — which are precisely the first deliverables of Step 0/3/6, not prose a plan document can contain. No open design decision requires the user. Recommendation: proceed to build; the schema/validator/scoring-spec land first and are the concrete discharge of the remaining findings.

