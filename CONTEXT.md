# TigerGraph Agentic Fraud Investigation (HHGOA)

The ubiquitous language for a hackathon build: an agentic fraud-investigation agent on TigerGraph, delivered as three comparable pipelines (Plain RAG → GraphRAG → Agentic GraphRAG) on one shared model to demonstrate relative lift. This file is a glossary only — no implementation details. Terms are aligned to the dataset README, which is authoritative for domain language.

## Fraud investigation domain

**Trigger**:
Why an alert exists. Exactly three types in the data: `risk_score` (the model scored a transaction high), `customer_report` (a cardholder disputes a charge), `analyst_request` (an analyst asks for a look).

**Case**:
The bank's internal investigation record — and Part 1 of every answer. Opened when fraud probability reaches 0.30, when evidence is requested, or when a customer disputes a charge. Has a `status` (`open` / `closed_fraud` / `closed_legitimate` / `escalated`) and progresses as evidence arrives. Written back into the graph so later investigations can retrieve it.
_Avoid_: ticket, alert, incident

**Evidence**:
A supporting fact, recorded as `claim` + `source` (`graph` / `document` / `customer` / `external`) + `ref` + the `entity_ids` it rests on.

**Verdict**:
The conclusion: `fraud`, `legitimate`, or `uncertain`. `uncertain` is valid and earns full credit on cases designed to be ambiguous when the actions follow policy.

**Fraud probability**:
Our calibrated 0–1 estimate that the flagged activity is fraud. Scored for calibration. Policy thresholds: open a case at ≥0.30; verify before blocking on a single signal below 0.70; stop at ≥0.85 or ≤0.15 (with two independent pieces of evidence).

**Next best action (NBA)**:
What the bank should do now — Part 3 of the answer. Chosen from a fixed set of 14 policy action identifiers (e.g. `ALLOW_TRANSACTION`, `DECLINE_TRANSACTION`, `MONITOR_CARD`, `MONITOR_CONNECTED_CARDS`, `WARN_CUSTOMER`, `VERIFY_WITH_CUSTOMER`, `STEP_UP_AUTH`, `BLOCK_CARD`, `BLOCK_ALL_CARDS`, `GENERATE_REPORT`, `CREATE_CASE`, `FILE_REPORT`, `ESCALATE_TO_ANALYST`, `CLOSE_NO_FRAUD`). Recorded twice: `initial` (before requested evidence) and `final` (after), with `what_changed`.
_Avoid_: response, remediation, resolution

**Approval route**:
The permission an action needs: `auto` (agent may act alone), `L1` (team lead), `L2` (fraud manager). Only `auto` actions may be executed by the agent; `L1`/`L2` are recommended with the route stated and wait for a human.

**Case memory**:
Prior cases retrieved to inform a new investigation, and cited in `similar_prior_cases`. Seeded by [[closed-case]] history and grown by writing each new [[Case]] back to the graph.
_Avoid_: history, cache

**Risk score**:
The bank model's 0–1 score on every transaction. A reason to look, never a verdict — often wrong both ways (above 0.7 most flagged transactions are legitimate; some fraud scores near zero). An input, not an answer.

**Fraud pattern**:
The kind of fraud, as an enum. Five documented patterns plus `undocumented` and `none`:
`card_testing` · `card_not_present_fraud` · `card_not_present_new_device` · `out_of_region_use` · `account_takeover` · `undocumented` · `none`.
The five are not the only patterns present; naming an `undocumented` one in your own words is explicitly scored.

**Card testing**:
A stolen number checked before use — three or more tiny online authorizations (often < $5), then a larger purchase.

**Card-not-present fraud**:
A number used online without the card; amounts/products inconsistent with the cardholder, often a burst of 2–4 within 48h. The `_new_device` variant adds an identity record marking the device `New` for the account.

**Out-of-region use**:
Card-present purchases in a billing region the cardholder has no history in, while normal home activity continues. Several days in one new region is a trip, not a clone.

**Account takeover**:
Mixed-channel activity inconsistent with the cardholder, often with device and match-flag anomalies — stolen credentials rather than a stolen number.

**Exposure**:
Total USD in the identified fraud episode: the sum of absolute amounts of every affected transaction, including the flagged one.

**SAR**:
Suspicious Activity Report — Part 2 of the answer, filed only when the policy calls for it (fraud confirmed or strongly suspected AND exposure > $1,000, or a shared device/region/ring link, or a coordinated/undocumented pattern). A stand-alone narrative: who, what, when, where, how, why. A report always has a case behind it; most cases never need one.

**Customer**:
The cardholder identity (`customer_id`, e.g. `C01234`), derived from the card issuer field. One customer can hold several cards.
_Avoid_: person, user, account

**Card**:
A payment card (`card_id`, e.g. `C01234-K1`) owned by a Customer; it makes Transactions.
_Avoid_: account

**Transaction**:
A single card transaction — `TransactionID`, `ts`, `TransactionAmt`, `ProductCD`, `channel`, `risk_score`, plus the 393 original Vesta columns (`card1–6`, `addr1–2`, email domains, `C/D/M`, `V1–V339`). The V/C/D/M columns are unnamed model features: usable as signals, but say so honestly in evidence.

**Channel**:
`in_person` (ProductCD `W`, no identity record) or `online` (all other product codes, identity record present).

**Device profile**:
An online transaction's device identity: `DeviceInfo` + OS + browser + screen (from `identity.csv`). A profile shared across many cards in a short window is a fraud signal.

**Email domain**:
Purchaser (`P_emaildomain`) or recipient (`R_emaildomain`) email domain.

**Billing region**:
`addr1`, an anonymized region code; `addr2` is the country (87 = home country).

**Closed case**:
A finished bank investigation from July–October (`closed_cases_history.csv`): `confirmed_fraud` or `cleared`, with a `pattern`, transactions, exposure, connected cards, and analyst notes. The only place ground truth is written down — both our labeled set and the agent's starting case memory.

**KnowledgeDocument**:
A vector-embedded chunk in TigerGraph's vector store for retrieval: closed-case narratives, the README's pattern section, the bank Fraud Policy, and the regulatory references (FinCEN, FATF, FFIEC, OFAC).

## Pipelines & evaluation

**Pipeline**:
One of the three end-to-end implementations under comparison. All three share the same model, data, and evaluation harness (see [[0001-three-isolated-pipelines]], [[0002-gemini-flash-shared-model]]).

**Plain RAG (P1)**:
Baseline. Answers a case using only vector-retrieved KnowledgeDocument text — no graph, no tools, single retrieve→answer pass. Relationship-blind.
_Avoid_: "RAG" used alone (ambiguous — say P1 or Plain RAG)

**GraphRAG (P2)**:
Retrieves *connected* context (a subgraph: card history, device/region/email neighbors, connected cards) from TigerGraph plus KnowledgeDocument chunks, in a single pass. Relationship-aware but non-adaptive (fixed retrieval, no tool loop, no case memory).

**Agentic GraphRAG (P3)**:
The full agent (see [[0003-single-agent-pydanticai]]). A multi-step plan→act→observe→pivot loop over MCP graph tools + knowledge search + case memory; produces the Case, NBA, and SAR, writes the Case back to the graph, and updates its recommendation as evidence arrives. The required deliverable.
_Avoid_: "the agent" when contrasting pipelines (say P3 or Agentic GraphRAG)

**Relative lift**:
The accuracy/quality improvement from P1 → P2 → P3 on the same model. The primary success metric. Measured on held-out **closed cases** (the labeled set); the 20 exam cases have no answer key we hold.

**Token efficiency**:
Tokens, tool calls, and latency per case — and not incidental: `tokens`, `tool_calls`, and `latency_s` are **required fields in every answer file**. Measured for all three pipelines.

**Case pack (exam)**:
The fixed 20 cases (`case_pack.csv`, November–December) every team is scored on against a hidden answer key. One JSON answer file per case (`<case_id>.json` in `cases/`). Distinct from the July–October closed cases, which seed case memory and serve as our labeled eval set.

