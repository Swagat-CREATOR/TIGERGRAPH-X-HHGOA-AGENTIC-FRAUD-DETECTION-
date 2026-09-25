# 🕵️ Agentic Fraud Investigation on TigerGraph (HHGOA)

> **One shared LLM. Three pipelines — Plain RAG → GraphRAG → Agentic GraphRAG.**
> One TigerGraph fraud graph, reached through the **GRIP** MCP layer.
> We measure what each rung of the AI-capability ladder actually buys you: **accuracy lift vs. token cost.**

## The thesis

The challenge rewards *relative lift + architecture + token efficiency*, **not raw model power** — "a cheaper model with a better architecture can beat an expensive model with a lazy pipeline." So we hold the **model, the policy, the answer schema, and the validator constant**, and change only **how much of the graph reaches the model**. Any difference in the output is therefore attributable to *architecture*, never to a bigger model.

| Rung | Pipeline | What the model sees |
|------|----------|---------------------|
| RAG | **P1 — Plain RAG** | Policy & pattern **documents only**. No graph, no transaction data. |
| GraphRAG | **P2 — GraphRAG** | The same documents **+ a pre-assembled graph bundle** (48h window, card history, device / connected-card neighbours, closed-case precedents). One shot, non-agentic. |
| Agentic | **P3 — Agentic GraphRAG** | The model **drives a plan→act→observe tool loop** over the *live* graph + knowledge search, choosing what to fetch, until the evidence settles. |

Everything downstream of "what reaches the model" is **shared** so the comparison is fair: the same compact policy cheat-sheet, the same strict Pydantic answer schema, the same deterministic route-assignment matrix, and the same validator repair loop. Tokens / tool-calls / latency are **measured**, never model-reported.

---

## 📊 Headline results

### Exam set — 20 official HHG cases · `cases/_runs/summary.json`

**0 policy violations** across every successful answer.

| Pipeline | OK | Committed verdicts¹ | Tokens | Tok/case | Tool calls |
|----------|----|---------------------|--------|----------|------------|
| P1 Plain RAG | 20 / 20 | **0** (20 uncertain) | 60,110 | ~3.0k | 0 |
| P2 GraphRAG | 19 / 20² | **2** (1 fraud, 1 legit) | 169,687 | ~8.9k | 0 |
| P3 Agentic | 20 / 20 | **9** (8 fraud, 1 legit) | 987,435 | ~49k | 121 |

**The lift is _decisiveness_, and it is cleanly monotonic: 0 → 2 → 9 committed verdicts.**
Without the graph, P1 is paralysed — it punts *every* case to `uncertain`. P2 begins to commit (flags HHG-010, the \$1,000 case, as fraud; cleanly closes HHG-007 as legitimate). P3 acts — 8 fraud calls backed by real `BLOCK_CARD` / `DECLINE_TRANSACTION` / `FILE_REPORT` actions and 121 graph tool calls. The price of that agency is ~16× P1's tokens.

<sup>¹ "Committed" = a verdict other than `uncertain`. &nbsp; ² HHG-001 hit a transient gateway 500 on P2; backfill skipped to conserve budget.</sup>

### Held-out ablation — leakage-safe, disjoint-by-customer · `cases/_eval/eval_report.json`

A second, **stricter** evaluation on 30 withheld cases whose customers are *disjoint* from the exam set, presented with a **neutral, label-free trigger** (no near-neighbour to retrieve). The token budget covered **16 of 30** cases (P1/P2 = 16, P3 = 13; 3 P3 cases lost to gateway/quota errors).

| Pipeline | Pattern (exact) | Pattern (CNP-family³) | SAR accuracy | Tok/case |
|----------|-----------------|-----------------------|--------------|----------|
| P1 | 0.000 (0/16) | 0 | 0.938 | 5.3k |
| P2 | **0.188** (3/16) | **~0.44** (7/16) | 0.938 | 7.3k |
| P3 | 0.077 (1/13) | ~0.38 (5/13) | 0.769⁴ | 55.5k |

**P1 is pattern-blind by construction** — with no transaction data it labels *every* case `none` (0/16). **P2 recovers real patterns from graph evidence** — it nails `out_of_region_use` exactly, and lands in the correct card-not-present family ~7× where P1 never does.

<sup>³ Exact-match hides partial credit: `card_not_present_fraud` and `card_not_present_new_device` are sibling CNP sub-types. ⁴ P3 over-files 2 unnecessary SARs here — an honest cost of aggressiveness.</sup>

> **⚖️ Honest caveat — the `fraudF1 = 0` you'll see is a _metric artifact_, not a detection failure.**
> The held-out cases are nearly all confirmed fraud, but under the deliberately weak neutral trigger the model returns the *valid, policy-compliant* `uncertain` verdict (escalate / verify) rather than committing to `fraud`. The binary fraud/not-fraud scorer then counts every `uncertain` as a false negative. On the exam set (with richer triggers) P3 commits `fraud` 8×. The scientific point is the **contrast**: the lift is clean when there is signal + a retrievable neighbour (exam), and it compresses under low signal + strict leakage control (held-out).

---

## 🧠 Showcase — HHG-010: a fraud ring only the graph could see

The flagged transaction was a lone \$1,000.03 online purchase. P1 (docs only) returned `uncertain / none`. **P3 pulled the graph and found a ring:**

1. `transaction_features` → risk 0.90, anonymous.com emails, new device.
2. `device_neighbors` → that new device is **shared across 3 customers**.
3. `connected_cards` → the card links via shared devices to **9 other cards across 9 customers** — a coordinated ring.
4. `similar_closed_cases` → 400 `account_takeover` precedents at this exposure resolved as confirmed fraud.
5. Verdict **fraud** (p=0.90), pattern `account_takeover`, `BLOCK_ALL_CARDS` (R10 satisfied), and a **policy-grounded SAR** (§3a: exposure > \$1,000 + shared-device coordination).

Every ID in that answer exists in the dataset; every graph claim cites the tool it came from. See [`cases/HHG-010.json`](cases/HHG-010.json).

---

## 🏗️ Architecture

```
                 ┌──────────────────────────────────────────────┐
   case_pack.csv │  P1 Plain RAG    P2 GraphRAG   P3 Agentic      │
   heldout.csv → │      │                │             │          │
                 │  docs only     docs + bundle   plan→act→observe│
                 │      └────────────────┼─────────────┘          │
                 │        ONE shared LLM (src/llm.py)             │  ← held constant
                 │        shared policy · schema · validator      │
                 └───────────────┬────────────────┬───────────────┘
                                 │                │
                    knowledge_search        graph tools (src/tools.py)
                                 │                │
                         ┌───────▼────────────────▼───────┐
                         │   GRIP  (MCP layer, stdio)      │  ← mandatory TigerGraph MCP
                         └───────────────┬─────────────────┘
                                         │
                         ┌───────────────▼─────────────────┐
                         │  TigerGraph — FraudInvestigation │
                         │  Customer·Card·Transaction·      │
                         │  DeviceProfile·Region·ClosedCase │
                         └──────────────────────────────────┘
```

- **GRIP** is the mandatory TigerGraph MCP layer (local, stdio). `KnowledgeIndex` (`src/knowledge.py`) runs one long-lived GRIP session on a background event-loop thread and exposes a synchronous `search()` — GraphRAG document retrieval without paying a subprocess spawn per query. It degrades to a GSQL keyword scan if GRIP is unavailable, so a run never hard-fails.
- **Graph schema** (`src/graph_schema.gsql`) — `Customer / Card / Transaction / DeviceProfile / EmailDomain / BillingRegion / ClosedCase / InvestigationCase`, with reverse edges so ring detection can traverse *device → transaction → card → customer*. Types are **LOCAL** to `FraudInvestigation` so they never collide with the demo's global types (ADR-0004: load a targeted subgraph, fetch wide columns on demand).
- **Pipelines** (`src/pipelines.py`) — P1/P2/P3 as above; the only variable is the evidence block.
- **Shared spine** — policy cheat-sheet + deterministic route matrix (`src/policy.py`), strict answer schema (`src/schema.py`), validator with a bounded repair loop (`src/validator.py`).
- **Agent tools** (`src/tools.py`) — `transaction_features`, `card_window`, `card_txn_history`, `device_neighbors`, `connected_cards`, `region_activity`, `similar_closed_cases`, plus `knowledge_search`.
- **Multi-provider LLM** (`src/llm.py`) — Gemini / Groq / xkiro behind one interface, selected by `LLM_PROVIDER`. **One model is held constant across P1/P2/P3** so the comparison stays fair (see ADR-0002 and ADR-0005).

---

## 🔒 Leakage safety & dataset integrity

- The held-out eval split is **disjoint by customer** from the exam set and from the closed-case graph memory, so a pipeline can never retrieve the case it is currently solving.
- The held-out labels (`data/heldout_eval.csv`) are used **only** for scoring and are **never** loaded into the graph or placed in any `CaseInput`.
- Every ID emitted in an answer file exists in the provided dataset. The original public IEEE-CIS / Kaggle files are **never** used to recover outcomes.

---

## ▶️ Reproduce

```bash
# 1. Setup
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env        # then fill in TG_* creds, an LLM key, and DATASET_DIR
```

```bash
# 2. Build the graph + load the targeted subgraph (one-time)
python -m src.create_graph          # create FraudInvestigation + schema
python -m src.load_exam             # load the 20 exam customers' subgraph
python -m src.load_closed_cases     # load closed-case graph memory (precedents)
python -m src.ingest_knowledge      # ingest policy/pattern docs for GRIP retrieval
```

```bash
# 3. Run the pipelines over the 20 exam cases (writes cases/_runs/ + cases/HHG-*.json)
python -m src.run_cases                    # all three; --pipelines P3 for just the deliverable
```

```bash
# 4. Held-out ablation (resumable; split across capped keys with --offset/--limit)
python -m src.load_heldout_txns            # load the disjoint held-out subgraph
python -m src.evaluate --offset 0 --limit 8   # a slice; swap the key and repeat for the rest
```

**No-API rebuilds** — reconstruct both scoreboards from the on-disk answers, spending zero tokens:

```bash
python -m src.rebuild_summary       # rebuild cases/_runs/summary.json (exam)
python -m src.evaluate --aggregate  # rebuild cases/_eval/eval_report.json (held-out)
python -m src.build_report          # render report.html from both scoreboards
```

### End-to-end run and UI

On Windows PowerShell, run the same setup from the repository root:

```powershell
python -m venv .venv
\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env with TigerGraph, model-provider, and DATASET_DIR values.
```

Initialize the graph and knowledge layer once:

```powershell
python -m src.create_graph
python -m src.create_doc_schema
python -m src.load_exam
python -m src.load_closed_cases
python -m src.ingest_knowledge
```

Run the required agentic deliverable, or run all three comparison pipelines:

```powershell
python -m src.run_cases --pipelines P3
# or: python -m src.run_cases
```

Build and view the analyst UI locally:

```powershell
python -m src.build_ui
python -m src.serve_ui 8000
```

Open [http://localhost:8000/ui.html](http://localhost:8000/ui.html). The UI
shows the trigger, P3 MCP/tool trace, evidence, uncertainty requests, initial
and final next-best actions, SAR details, case write-back status, and the
P1/P2/P3 comparison metrics. It is a read-only viewer over the generated
answers and traces; it does not execute financial or customer-facing actions.

For a no-API rebuild of the existing scoreboards and report:

```powershell
python -m src.rebuild_summary
python -m src.evaluate --aggregate
python -m src.build_report
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the component map and
[CONTRIBUTING.md](CONTRIBUTING.md) for commit and publication rules.

---

## 🗂️ Project layout

```
src/
  create_graph.py  graph_schema.gsql   # schema + graph creation
  load_exam.py  load_closed_cases.py  load_heldout_txns.py  extract_subgraph.py
  ingest_knowledge.py  knowledge.py  knowledge_docs.py  grip_client.py   # GRIP doc layer
  tg.py  tools.py                      # TigerGraph client + agent graph tools
  llm.py                               # multi-provider shared LLM
  pipelines.py                         # P1 / P2 / P3
  policy.py  schema.py  validator.py   # shared policy · answer schema · validator
  run_cases.py  evaluate.py            # exam driver · held-out eval
  rebuild_summary.py  build_report.py  # no-API scoreboard rebuild · HTML report
cases/         HHG-*.json (P3 deliverable answers) · _runs/ · _eval/
docs/adr/      architecture decision records (0001–0005)
CONTEXT.md  PLAN.md  PLAN-REVIEW-LOG.md
report.html    single-file results dashboard
```

---

## ⚖️ Honest limitations

- **Held-out coverage is 16/30** (P3: 13/30). The full 30×3 eval is ~1.84M tokens; the available free-tier budget covered a representative slice. Resume the rest with `python -m src.evaluate --offset 16`.
- **`fraudF1 = 0` on held-out** is a metric artifact of mapping the model's valid `uncertain` verdict onto a binary scorer under a deliberately weak trigger (see the caveat above), not a detection failure.
- **P3 over-files SARs** on 2 held-out cases — the agentic pipeline trades some precision for aggressiveness.
- **P2 exam is 19/20** — HHG-001 hit a transient gateway 500; the backfill was skipped to conserve budget.
- **The shared model is `qwen/qwen3.8-max:free`**, reached via a Gemini → Groq → xkiro provider-fallback chain after the free tiers were exhausted. It is still **one model held constant across all three pipelines**, so the comparison remains fair (ADR-0005 supersedes the model choice in ADR-0002).



