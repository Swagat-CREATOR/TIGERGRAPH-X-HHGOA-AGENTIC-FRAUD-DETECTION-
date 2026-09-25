"""Write each finished investigation back into the graph as an InvestigationCase.

The dataset README + the challenge PDF both require that "the case should also be
written to the graph". This closes that loop: every deliverable answer in
``cases/HHG-*.json`` becomes an ``InvestigationCase`` vertex in FraudInvestigation,
linked by ``CASE_ON_CARD`` -> Card and ``CASE_INVOLVES`` -> Transaction, and the
answer file's ``written_to_graph`` / ``graph_case_id`` fields are set to reflect it.

Two entry points:
  * ``write_case_to_graph(conn, answer)`` — reusable; called live from run_cases.py
    right after P3 emits, so a fresh run is faithful to the spec.
  * ``python -m src.write_cases`` — NO-API backfill over the 20 on-disk answers
    (spends zero LLM tokens). Idempotent: re-running upserts the same vertices.

The answer file is re-serialised through the strict CaseAnswer model, so the only
change is the two graph fields — README-exact field order/format is preserved.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.schema import CaseAnswer

CASES = Path("cases")
GRAPH = "FraudInvestigation"


def _gid(case_id: str) -> str:
    return f"IC-{case_id}"


def write_case_to_graph(conn, answer: CaseAnswer, created_at: str = "") -> str:
    """Upsert one InvestigationCase (+ edges) into the graph. Returns graph_case_id.

    IDs cited in the answer (affected_txn_ids / connected_card_ids) were produced
    by graph tool calls against this same graph, so the edge targets already exist.
    """
    c = answer.case
    gid = _gid(answer.case_id)
    created = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.upsertVertices("InvestigationCase", [(gid, {
        "case_id": answer.case_id,
        "verdict": c.verdict.value,
        "pattern": c.pattern.value,
        "fraud_probability": c.fraud_probability,
        "exposure_usd": c.exposure_usd,
        "status": c.status.value,
        "summary": c.summary,
        "created_at": created,
    })])
    cards = [cid for cid in c.connected_card_ids if cid]
    if cards:
        conn.upsertEdges("InvestigationCase", "CASE_ON_CARD", "Card",
                         [(gid, cid, {}) for cid in cards])
    txns = [t for t in c.affected_txn_ids if t]
    if txns:
        conn.upsertEdges("InvestigationCase", "CASE_INVOLVES", "Transaction",
                         [(gid, t, {}) for t in txns])
    return gid


def _backfill() -> None:
    """No-API pass: write all 20 deliverable answers to the graph and flag them."""
    from src.tg import connect

    files = sorted(p for p in CASES.glob("HHG-*.json")
                   if not p.name.endswith(".trace.json"))
    if not files:
        print("no cases/HHG-*.json found — nothing to write.")
        return
    conn = connect(GRAPH)
    print(f"connected to {GRAPH}; writing {len(files)} investigation cases", flush=True)
    n_cards = n_txns = 0
    for p in files:
        answer = CaseAnswer.model_validate_json(p.read_text(encoding="utf-8"))
        gid = write_case_to_graph(conn, answer)
        # reflect the write in the deliverable, preserving README-exact shape
        answer.case.written_to_graph = True
        answer.case.graph_case_id = gid
        p.write_text(answer.to_json(), encoding="utf-8")
        n_cards += len([x for x in answer.case.connected_card_ids if x])
        n_txns += len([x for x in answer.case.affected_txn_ids if x])
        print(f"  {answer.case_id} -> {gid}  "
              f"[{answer.case.verdict.value}] cards={len(answer.case.connected_card_ids)} "
              f"txns={len(answer.case.affected_txn_ids)}", flush=True)
    total = conn.getVertexCount("InvestigationCase")
    print(f"\nInvestigationCase vertices now in graph: {total}")
    print(f"edges upserted: CASE_ON_CARD~{n_cards}, CASE_INVOLVES~{n_txns}")
    print("answer files updated: written_to_graph=true, graph_case_id set.")


if __name__ == "__main__":
    _backfill()

