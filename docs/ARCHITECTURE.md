# HHGOA architecture

## System purpose

HHGOA is an agentic fraud-investigation system built around a TigerGraph
`FraudInvestigation` graph. It receives a case trigger, gathers targeted
evidence, assesses fraud pattern and confidence, recommends policy-compliant
next-best actions, drafts a SAR when required, and writes the investigation
back to graph memory.

The implementation deliberately compares three evidence strategies while
holding the model, policy, answer schema, and validator constant:

| Pipeline | Evidence supplied to the model | Behavior |
| --- | --- | --- |
| P1 Plain RAG | Retrieved policy and pattern documents | One structured model call; no case graph evidence |
| P2 GraphRAG | The same documents plus a fixed graph bundle | One-shot, non-agentic graph-grounded decision |
| P3 Agentic GraphRAG | Live graph and knowledge tools selected by the model | Plan -> act -> observe loop; required deliverable |

## Runtime flow

1. A case trigger identifies the case, customer, card, and flagged transaction.
2. The selected pipeline retrieves policy/pattern knowledge and, for P2/P3,
   targeted graph evidence.
3. P3 selects tools such as `transaction_features`, `card_window`,
   `device_neighbors`, `connected_cards`, `region_activity`, and
   `similar_closed_cases` until the stop rule is satisfied.
4. The shared LLM emits a strict Pydantic-compatible answer.
5. Deterministic route assignment, schema validation, and bounded policy repair
   run after generation.
6. The P3 answer is written as `InvestigationCase` graph memory and emitted as
   `cases/<case_id>.json`; the MCP/tool trace is emitted beside it.
7. `build_ui` renders the case answers, traces, evidence, uncertainty, actions,
   and P1/P2/P3 measurements into the local analyst UI.

## TigerGraph and GRIP

The `FraudInvestigation` graph contains `Customer`, `Card`, `Transaction`,
`DeviceProfile`, `EmailDomain`, `BillingRegion`, `ClosedCase`, and
`InvestigationCase` vertices with relationship edges for ownership,
transactions, devices, regions, history, precedents, and case write-back.

The GRIP MCP server is the primary local stdio interface. Its document layer
uses `Paper`, `Author`, `Concept`, and `PaperEmb`, including the TigerGraph
vector attribute used by the GraphRAG knowledge layer. Direct GSQL is only the
adapter fallback when GRIP is unavailable; the agent-facing tool signatures
remain the same.

## Controls and evaluation

- The same policy cheat-sheet is used in P1, P2, and P3.
- Approval routes are assigned deterministically in `src/policy.py`.
- `src/schema.py` rejects malformed or incomplete case records.
- `src/validator.py` checks policy violations and triggers bounded repair.
- LLM tokens, tool calls, and latency are measured by the harness.
- Held-out labels are used only for scoring and are excluded from the graph,
  case inputs, and closed-case memory.
- The UI exposes the tool trace and measurements so the investigation is
  inspectable rather than only presenting a final narrative.

## Mapping to the challenge brief

The PDF brief is treated as the requirements document, not as a command to
copy its example architecture or use any specific vendor/model beyond the
required TigerGraph components. This repository implements the required graph,
GSQL, MCP, GraphRAG, UI, case outputs, graph write-back, controlled actions,
explainability, memory, and stop-rule flow. Framework and LLM choices remain
project choices documented in the ADRs.

