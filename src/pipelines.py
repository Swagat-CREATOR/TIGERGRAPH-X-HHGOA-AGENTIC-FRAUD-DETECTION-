"""The three comparable pipelines — P1 plain RAG, P2 GraphRAG, P3 agentic
GraphRAG — over ONE shared Gemini model (src/llm.py).

They differ only in what context reaches the model:
  * P1  document retrieval only (GRIP knowledge_search on the trigger). No graph.
  * P2  the same documents PLUS a fixed, pre-assembled graph bundle (window,
        history, device/connected neighbours, precedents). One shot, non-agentic.
  * P3  the model drives a plan->act->observe tool loop (src/tools.py +
        knowledge_search), choosing what to fetch, then emits the answer.

Everything downstream is shared so the comparison is fair: the same compact
policy cheat-sheet in the system prompt (differentiator is case EVIDENCE, not
policy knowledge), the same strict answer schema (schema.py), the same
deterministic route fix + validator repair loop. Tokens/tool_calls/latency are
measured, not model-reported.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from pydantic import ValidationError

from src import policy, tools
from src.knowledge import KnowledgeIndex
from src.llm import LLM, ToolSpec
from src.schema import Action, CaseAnswer
from src.validator import check


@dataclass
class CaseInput:
    case_id: str
    opened_at: str
    trigger_type: str
    trigger_text: str
    flagged_txn_id: str
    card_id: str
    customer_id: str
    risk_score: str

    def brief(self) -> str:
        rs = f", model risk_score={self.risk_score}" if self.risk_score else ""
        return (f"Case {self.case_id} opened {self.opened_at}. Trigger "
                f"({self.trigger_type}): {self.trigger_text} Flagged transaction "
                f"{self.flagged_txn_id} on card {self.card_id}, customer "
                f"{self.customer_id}{rs}.")


# --------------------------------------------------------------------------- #
# Shared system prompt — the SAME compact, faithful policy cheat-sheet for all
# three pipelines. The differentiator between P1/P2/P3 is the case EVIDENCE that
# reaches the model, never the policy knowledge, so this block is identical.
# --------------------------------------------------------------------------- #
_POLICY_CHEATSHEET = f"""\
You are a bank fraud-investigation agent. Investigate ONE flagged transaction and
return a decision that complies with Fraud Policy v1.0. Reason from the EVIDENCE
you are given; never invent transactions, cards, customers, or IDs. Every ID in
your answer must be one that appears in the provided evidence.

FRAUD POLICY (obey exactly):
- Open a case (CREATE_CASE) once fraud_probability >= {policy.CASE_CREATE_P}.
- R1: never BLOCK_CARD / BLOCK_ALL_CARDS / DECLINE_TRANSACTION on a single weak
  signal (fraud_probability < {policy.VERIFY_MAX_P}) without first proposing
  VERIFY_WITH_CUSTOMER or STEP_UP_AUTH in the INITIAL actions.
- R8: an 'uncertain' verdict with exposure > ${policy.ESCALATE_EXPOSURE_USD:.0f}
  MUST include ESCALATE_TO_ANALYST in final actions.
- R10: BLOCK_ALL_CARDS only with 2+ compromised cards (flagged card + >=1
  connected card) OR confirmed credential compromise (account_takeover).
- §3a: FILE_REPORT must be accompanied by CREATE_CASE. File a SAR iff fraud is
  confirmed OR strongly suspected (p >= {policy.STRONGLY_SUSPECTED_P}) AND one of:
  exposure > ${policy.SAR_EXPOSURE_USD:.0f}; activity connects to a shared
  device/region/another customer's fraud; pattern is coordinated or undocumented.
- §6 stop: stop investigating when p >= {policy.STOP_CONFIDENT_HI} or
  p <= {policy.STOP_CONFIDENT_LO} with >=2 independent pieces of evidence.
- A 'legitimate' verdict carries NO affected_txn_ids, exposure_usd=0, and no SAR.
- Approval routes are assigned deterministically downstream; still output a route
  per action (auto/L1/L2) as your best guess.

PATTERNS (enum): card_testing, card_not_present_fraud, card_not_present_new_device,
out_of_region_use, account_takeover, undocumented, none. Use 'undocumented' only
for a real pattern not in this list (then fill pattern_description); use 'none'
when there is no fraud pattern.

ACTIONS (enum): ALLOW_TRANSACTION, DECLINE_TRANSACTION, MONITOR_CARD,
MONITOR_CONNECTED_CARDS, WARN_CUSTOMER, VERIFY_WITH_CUSTOMER, STEP_UP_AUTH,
BLOCK_CARD, BLOCK_ALL_CARDS, GENERATE_REPORT, CREATE_CASE, FILE_REPORT,
ESCALATE_TO_ANALYST, CLOSE_NO_FRAUD."""

_ANSWER_SCHEMA = """\
Return ONLY one JSON object, no prose, matching EXACTLY these keys (no extras):
{
  "case_id": str,
  "case": {
    "status": "open|closed_fraud|closed_legitimate|escalated",
    "verdict": "fraud|legitimate|uncertain",
    "fraud_probability": float 0..1,
    "pattern": <pattern enum>,
    "pattern_description": "" (non-empty ONLY if pattern=undocumented, else ""),
    "affected_txn_ids": [str], "first_suspicious_txn_id": str,
    "connected_card_ids": [str], "connected_device_profiles": [str],
    "exposure_usd": float,
    "evidence": [{"claim": str, "source": "graph|document|customer|external",
                  "ref": str, "entity_ids": [str]}],
    "similar_prior_cases": [str], "summary": str,
    "written_to_graph": false, "graph_case_id": ""
  },
  "evidence_requests": [{"type": "customer_validation|step_up_auth|analyst_info",
                         "asked_after_step": int>=0, "assumed_response": str}],
  "next_best_actions": {
    "initial": [{"action": <action enum>, "route": "auto|L1|L2", "reason": "cite Rn/§"}],
    "final":   [{"action": <action enum>, "route": "auto|L1|L2", "reason": "cite Rn/§"}],
    "what_changed": str ("nothing" if final==initial)
  },
  "sar": {"file": bool, "reason": str, "narrative": "", "subjects": [],
          "total_amount_usd": 0.0, "activity_dates": []},
  "stop_reason": str, "tool_calls": 0, "tokens": 0, "latency_s": 0.0
}
When sar.file=true: narrative non-empty, subjects=[customer_id...],
total_amount_usd=exposure, activity_dates=[first_date, last_date] (YYYY-MM-DD).
When sar.file=false: keep narrative="", subjects=[], total_amount_usd=0.0,
activity_dates=[]. sar.file must equal whether FILE_REPORT is in final actions.
For each evidence item: when source='graph', ref = the tool/query name it came
from; when source='document', ref MUST be one of the exact `document:<ID>` tags
shown in the retrieved documents above (e.g. document:POLICY-R1), not a paraphrase.
Set tool_calls/tokens/latency_s to 0 — they are measured and filled in for you."""


def _docs_block(index: KnowledgeIndex, query: str, k: int = 5) -> tuple[str, list[dict]]:
    """Knowledge retrieval shared by all three pipelines (P1's only context)."""
    hits = index.search(query, top_k=k)
    lines = [f"[document:{h['id']}] {h.get('title','')}\n{h.get('snippet','')}"
             for h in hits]
    return ("RETRIEVED POLICY & PATTERN DOCUMENTS:\n" + "\n\n".join(lines)), hits


def _apply_measured_and_routes(raw: dict, measured: dict) -> dict:
    """Deterministic post-processing before validation: overwrite the model's
    route guesses with the policy matrix, and stamp the measured counters."""
    exposure = float((raw.get("case") or {}).get("exposure_usd") or 0.0)
    nba = raw.get("next_best_actions") or {}
    for key in ("initial", "final"):
        for item in nba.get(key, []) or []:
            try:
                item["route"] = policy.required_route(
                    Action(item.get("action")), exposure).value
            except (ValueError, KeyError):
                pass  # unknown action -> let schema validation report it
    raw["tool_calls"] = measured.get("tool_calls", 0)
    raw["tokens"] = measured.get("tokens", 0)
    raw["latency_s"] = measured.get("latency_s", 0.0)
    return raw


def _emit(llm: LLM, system: str, user: str, case: CaseInput,
          measured_fn) -> tuple[CaseAnswer, list[str]]:
    """Generate -> deterministic route fix -> validate -> bounded repair loop.

    `measured_fn()` returns the live {tool_calls,tokens,latency_s} at emit time
    (tokens accumulate on the shared LLM, so it is read late). Returns the valid
    CaseAnswer and the list of any residual violations (empty when clean)."""
    prompt = user
    last_err = ""
    for _ in range(3):
        raw = llm.generate_json(system, prompt)
        raw["case_id"] = case.case_id  # never let the model rename the case
        raw = _apply_measured_and_routes(raw, measured_fn())
        try:
            ans = CaseAnswer(**raw)
        except ValidationError as ex:
            last_err = str(ex)[:800]
            prompt = (f"{user}\n\nYour previous answer FAILED schema validation:\n"
                      f"{last_err}\nReturn corrected JSON only.")
            continue
        viols = check(ans)
        if not viols:
            return ans, []
        last_err = "; ".join(viols)
        prompt = (f"{user}\n\nYour previous answer VIOLATED policy:\n{last_err}\n"
                  f"Fix these and return corrected JSON only.")
    # Exhausted repairs: surface the best effort with residual violations.
    raw = _apply_measured_and_routes(llm.generate_json(system, prompt), measured_fn())
    raw["case_id"] = case.case_id
    ans = CaseAnswer(**raw)  # if this still raises, the case genuinely failed
    return ans, check(ans)


@dataclass
class PipelineResult:
    name: str            # "P1" | "P2" | "P3"
    answer: CaseAnswer
    trace: "CaseTrace"
    violations: list[str]


# --------------------------------------------------------------------------- #
# P1 — Plain RAG: knowledge documents only, one structured call. No graph.
# --------------------------------------------------------------------------- #
def run_p1(case: CaseInput, llm: LLM, index: KnowledgeIndex) -> PipelineResult:
    from src.schema import CaseTrace
    t0, tok0 = time.time(), llm.tokens
    docs, _ = _docs_block(index, case.trigger_text)
    user = (f"{case.brief()}\n\n{docs}\n\n"
            "You have ONLY the policy/pattern documents above — no transaction or "
            "graph data for this specific card. Investigate and decide.\n\n"
            f"{_ANSWER_SCHEMA}")
    measured = lambda: {"tool_calls": 0, "tokens": llm.tokens - tok0,
                        "latency_s": time.time() - t0}
    ans, viols = _emit(llm, _POLICY_CHEATSHEET, user, case, measured)
    trace = CaseTrace(case_id=case.case_id, model_version=llm.model)
    return PipelineResult("P1", ans, trace, viols)


# --------------------------------------------------------------------------- #
# P2 — GraphRAG: documents + a fixed, pre-assembled graph context bundle.
# One shot, non-agentic (the model does not choose what to fetch).
# --------------------------------------------------------------------------- #
def _graph_bundle(case: CaseInput) -> dict:
    """Deterministic one-shot context: everything a competent analyst would pull
    up front for this flagged txn. Same tool implementations P3 calls, fixed here."""
    txn = case.flagged_txn_id
    anchor = tools.card_for_txn(txn)
    card = anchor.get("card_id") or case.card_id
    feats = tools.transaction_features(txn)
    exposure = feats.get("amount", 0.0) if feats.get("found") else 0.0
    return {
        "flagged_transaction": feats,
        "card": anchor,
        "window_48h": tools.card_window(txn, hours=48.0),
        "recent_history": tools.card_txn_history(card, limit=25),
        "device_neighbors": tools.device_neighbors(txn),
        "connected_cards": tools.connected_cards(card),
        "similar_closed_cases": tools.similar_closed_cases(
            exposure_usd=float(exposure or 0.0), top_k=5),
    }


def run_p2(case: CaseInput, llm: LLM, index: KnowledgeIndex) -> PipelineResult:
    from src.schema import CaseTrace
    t0, tok0 = time.time(), llm.tokens
    docs, _ = _docs_block(index, case.trigger_text)
    bundle = _graph_bundle(case)
    user = (f"{case.brief()}\n\n{docs}\n\n"
            "GRAPH EVIDENCE for this card (pre-assembled from TigerGraph):\n"
            f"{json.dumps(bundle, default=str)[:9000]}\n\n"
            "Use both the documents and the graph evidence. Cite graph facts with "
            "source='graph' and the tool/field they came from; cite documents with "
            f"source='document'.\n\n{_ANSWER_SCHEMA}")
    measured = lambda: {"tool_calls": 0, "tokens": llm.tokens - tok0,
                        "latency_s": time.time() - t0}
    ans, viols = _emit(llm, _POLICY_CHEATSHEET, user, case, measured)
    trace = CaseTrace(case_id=case.case_id, model_version=llm.model)
    return PipelineResult("P2", ans, trace, viols)


# --------------------------------------------------------------------------- #
# P3 — Agentic GraphRAG: the model drives a plan->act->observe tool loop over the
# live graph + knowledge search, choosing what to fetch, then emits the answer.
# --------------------------------------------------------------------------- #
_TOOL_SPECS = [
    ToolSpec("knowledge_search",
             "Search fraud policy & pattern documents. Use to ground the pattern "
             "label, SAR rule, and routing in policy.",
             {"type": "object", "properties": {
                 "query": {"type": "string"},
                 "top_k": {"type": "integer"}}, "required": ["query"]}),
    ToolSpec("transaction_features",
             "Full features for one transaction (amount, region, emails, product, "
             "channel, risk_score, joined device profile).",
             {"type": "object", "properties": {"txn_id": {"type": "string"}},
              "required": ["txn_id"]}),
    ToolSpec("card_for_txn", "The card and owning customer behind a transaction.",
             {"type": "object", "properties": {"txn_id": {"type": "string"}},
              "required": ["txn_id"]}),
    ToolSpec("card_window",
             "All transactions on the flagged txn's card within +/- hours of it "
             "(reveals card-testing bursts / CNP sprees).",
             {"type": "object", "properties": {
                 "txn_id": {"type": "string"}, "hours": {"type": "number"}},
              "required": ["txn_id"]}),
    ToolSpec("card_txn_history",
             "Recent transactions on a card, newest first (the cardholder's normal).",
             {"type": "object", "properties": {
                 "card_id": {"type": "string"}, "limit": {"type": "integer"}},
              "required": ["card_id"]}),
    ToolSpec("device_neighbors",
             "Other cards/customers that transacted from the SAME device profile as "
             "the flagged txn (core fraud-ring signal, R6/R10).",
             {"type": "object", "properties": {"txn_id": {"type": "string"}},
              "required": ["txn_id"]}),
    ToolSpec("connected_cards",
             "Cards linked to this card by a shared device profile (ring / "
             "BLOCK_ALL_CARDS evidence).",
             {"type": "object", "properties": {"card_id": {"type": "string"}},
              "required": ["card_id"]}),
    ToolSpec("region_activity",
             "Cards/customers active in a billing region (out-of-region reasoning).",
             {"type": "object", "properties": {
                 "region": {"type": "string"}, "limit": {"type": "integer"}},
              "required": ["region"]}),
    ToolSpec("similar_closed_cases",
             "Resolved closed-case precedents from graph memory, filtered by pattern "
             "and ranked by nearest exposure (how the bank resolved like cases).",
             {"type": "object", "properties": {
                 "pattern": {"type": "string"},
                 "exposure_usd": {"type": "number"},
                 "top_k": {"type": "integer"}}, "required": []}),
]


def _p3_dispatch(name: str, args: dict, index: KnowledgeIndex):
    if name == "knowledge_search":
        return {"hits": index.search(args.get("query", ""),
                                     int(args.get("top_k", 5)))}
    fn = tools.GRAPH_TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    return fn(**args)


def run_p3(case: CaseInput, llm: LLM, index: KnowledgeIndex) -> PipelineResult:
    from src.schema import CaseTrace, ToolCallRecord
    t0, tok0 = time.time(), llm.tokens
    loop_system = (_POLICY_CHEATSHEET + "\n\nYou investigate by CALLING TOOLS in a "
                   "plan->act->observe loop. Start from the flagged transaction: "
                   "pull its features, scan the card's window/history for a burst or "
                   "anomaly, check device/connected cards for a ring, and retrieve "
                   "precedents and the governing policy. Stop calling tools once the "
                   "evidence settles (§6) and summarise your findings in plain text.")
    final_text, raw_trace = llm.run_tool_loop(
        loop_system, case.brief(), _TOOL_SPECS,
        lambda n, a: _p3_dispatch(n, a, index), max_steps=8)

    notes = "\n".join(
        f"- {r['tool']}({json.dumps(r['args'])}): {r['result_summary']}"
        for r in raw_trace) or "(no tools called)"
    user = (f"{case.brief()}\n\nYou investigated with these tool calls and results:\n"
            f"{notes[:8000]}\n\nYour investigation summary:\n{final_text[:2000]}\n\n"
            "Now emit the final structured decision. Cite graph-derived facts with "
            "source='graph' (ref = the tool name) and policy/pattern facts with "
            f"source='document'.\n\n{_ANSWER_SCHEMA}")
    measured = lambda: {"tool_calls": len(raw_trace), "tokens": llm.tokens - tok0,
                        "latency_s": time.time() - t0}
    ans, viols = _emit(llm, _POLICY_CHEATSHEET, user, case, measured)

    tool_records = [ToolCallRecord(
        step=int(r.get("step", 0)), tool=r.get("tool", ""),
        args=r.get("args", {}) or {},
        ok=not str(r.get("result_summary", "")).startswith("ERROR"),
        result_summary=str(r.get("result_summary", ""))[:300]) for r in raw_trace]
    trace = CaseTrace(case_id=case.case_id, model_version=llm.model,
                      tool_trace=tool_records)
    return PipelineResult("P3", ans, trace, viols)


PIPELINES = {"P1": run_p1, "P2": run_p2, "P3": run_p3}


def load_cases(path: str | None = None) -> list[CaseInput]:
    """Read the 20 case_pack rows into CaseInput (README trigger fields).

    Defaults to ``$DATASET_DIR/case_pack.csv`` (same source as load_exam.py /
    extract_subgraph.py) so the driver is not sensitive to the cwd."""
    import csv
    from pathlib import Path
    from dotenv import dotenv_values
    if path is None:
        path = str(Path(dotenv_values(".env")["DATASET_DIR"]) / "case_pack.csv")
    rows: list[CaseInput] = []
    with open(Path(path), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(CaseInput(
                case_id=r["case_id"], opened_at=r["opened_at"],
                trigger_type=r["trigger_type"], trigger_text=r["trigger_text"],
                flagged_txn_id=r["flagged_txn_id"], card_id=r["card_id"],
                customer_id=r["customer_id"], risk_score=r.get("risk_score", "")))
    return rows


if __name__ == "__main__":
    # Single-case verification (minimal API spend): pick one case + one pipeline.
    #   python -m src.pipelines [CASE_ID] [P1|P2|P3]
    import sys
    from src.llm import make_llm

    case_id = sys.argv[1] if len(sys.argv) > 1 else "HHG-001"
    which = sys.argv[2] if len(sys.argv) > 2 else "P3"
    case = next(c for c in load_cases() if c.case_id == case_id)

    idx = KnowledgeIndex()
    print(f"knowledge backend: {idx.backend}")
    llm = make_llm()
    res = PIPELINES[which](case, llm, idx)
    idx.close()

    print(f"\n=== {res.name} {case_id} ===")
    print(res.answer.to_json())
    print(f"\nmeasured: tool_calls={res.answer.tool_calls} "
          f"tokens={res.answer.tokens} latency={res.answer.latency_s:.1f}s")
    print("violations:", res.violations or "none")
    if res.trace.tool_trace:
        print("tool_trace:")
        for tr in res.trace.tool_trace:
            print(f"  [{tr.step}] {tr.tool}{tr.args} -> {tr.result_summary[:80]}")

