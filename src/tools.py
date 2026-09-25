"""Agent tool layer over the live FraudInvestigation graph (the P3 "act" step,
also reused to assemble P2's deterministic context).

Each tool is a plain function returning JSON-able dicts, so the same
implementations back the Gemini function-calling loop (P3), the fixed GraphRAG
context bundle (P2), and direct unit tests. Graph reads go through pyTigerGraph
INTERPRET QUERY on this small subgraph (26k txns); transaction_features reads
the pruned CSV cache (ADR-0004: V/C/D/M columns live in the CSV, not the graph).

knowledge_search + write_case are NOT here: knowledge_search needs the async
GRIP session the pipeline owns, and write_case mutates the graph — both live in
the pipeline layer so this module stays a pure, side-effect-free read layer.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from src.tg import connect

DATA = Path("data")
_CONN = None


def _c():
    global _CONN
    if _CONN is None:
        _CONN = connect("FraudInvestigation")
    return _CONN


def _q(gsql: str) -> list:
    """Run an INTERPRET QUERY block and return the raw result list."""
    return _c().runInterpretedQuery(gsql)


def _attrs(vlist: list) -> list[dict]:
    return [v["attributes"] for v in vlist]


# placeholder-tools


def card_for_txn(txn_id: str) -> dict:
    """The card that made a transaction, with the owning customer. The flagged
    txn's card anchors an investigation."""
    res = _q(f'''
    INTERPRET QUERY () FOR GRAPH FraudInvestigation {{
      S = {{Transaction.*}};
      R = SELECT c FROM S:t -(MADE_reverse:e)- Card:c WHERE t.txn_id == "{txn_id}";
      PRINT R;
    }}''')
    rows = _attrs(res[0]["R"]) if res and res[0]["R"] else []
    if not rows:
        return {"txn_id": txn_id, "card_id": None, "customer_id": None}
    a = rows[0]
    return {"txn_id": txn_id, "card_id": a["card_id"], "customer_id": a["customer_id"]}


def card_txn_history(card_id: str, limit: int = 40) -> dict:
    """Recent transactions on a card, newest first — establishes the cardholder's
    'normal' (amounts, channels, regions) so anomalies stand out."""
    res = _q(f'''
    INTERPRET QUERY () FOR GRAPH FraudInvestigation {{
      S = {{Card.*}};
      T = SELECT t FROM S:c -(MADE:e)- Transaction:t WHERE c.card_id == "{card_id}"
          ORDER BY t.dt DESC LIMIT {int(limit)};
      PRINT T;
    }}''')
    txns = _attrs(res[0]["T"]) if res and res[0]["T"] else []
    out = [{"txn_id": t["txn_id"], "amount": t["amount"], "ts": t["ts"],
            "channel": t["channel"], "product_cd": t["product_cd"],
            "risk_score": t["risk_score"], "region": t["addr1"],
            "p_email": t["p_email"]} for t in txns]
    return {"card_id": card_id, "n": len(out), "transactions": out}


def card_window(txn_id: str, hours: float = 48.0) -> dict:
    """All transactions on the flagged txn's card within +/- `hours` of it —
    the burst that reveals card testing (many tiny auths) or a CNP spree."""
    anchor = card_for_txn(txn_id)
    if not anchor["card_id"]:
        return {"txn_id": txn_id, "card_id": None, "window": []}
    span = int(hours * 3600)
    res = _q(f'''
    INTERPRET QUERY () FOR GRAPH FraudInvestigation {{
      S = {{Transaction.*}};
      F = SELECT t FROM S:t WHERE t.txn_id == "{txn_id}";
      INT anchor_dt;
      F = SELECT t FROM F:t ACCUM anchor_dt = t.dt;
      C = {{Card.*}};
      W = SELECT t FROM C:c -(MADE:e)- Transaction:t
          WHERE c.card_id == "{anchor['card_id']}"
          AND t.dt >= anchor_dt - {span} AND t.dt <= anchor_dt + {span}
          ORDER BY t.dt ASC;
      PRINT W;
    }}''')
    txns = _attrs(res[0]["W"]) if res and res[0]["W"] else []
    out = [{"txn_id": t["txn_id"], "amount": t["amount"], "ts": t["ts"],
            "channel": t["channel"], "product_cd": t["product_cd"],
            "risk_score": t["risk_score"], "region": t["addr1"]} for t in txns]
    return {"txn_id": txn_id, "card_id": anchor["card_id"], "hours": hours,
            "n": len(out), "window": out}


# placeholder-tools-2


def device_neighbors(txn_id: str) -> dict:
    """Other cards/customers that transacted from the SAME device profile as the
    flagged txn — the core ring signal (README: 'devices and regions connect
    people'). A single device behind many cards points to a fraud ring (R6)."""
    res = _q(f'''
    INTERPRET QUERY () FOR GRAPH FraudInvestigation {{
      S = {{Transaction.*}};
      D = SELECT d FROM S:t -(FROM_DEVICE:e)- DeviceProfile:d WHERE t.txn_id == "{txn_id}";
      T2 = SELECT t2 FROM D:d -(FROM_DEVICE_reverse:e)- Transaction:t2;
      R = SELECT c FROM T2:t2 -(MADE_reverse:e)- Card:c;
      PRINT D, R;
    }}''')
    dev = _attrs(res[0]["D"]) if res and res[0]["D"] else []
    cards = _attrs(res[0]["R"]) if res and res[0]["R"] else []
    device_id = dev[0]["device_id"] if dev else None
    seen, out = set(), []
    for c in cards:
        if c["card_id"] in seen:
            continue
        seen.add(c["card_id"])
        out.append({"card_id": c["card_id"], "customer_id": c["customer_id"]})
    return {"txn_id": txn_id, "device_id": device_id,
            "device_info": dev[0].get("device_info") if dev else None,
            "is_new": dev[0].get("is_new") if dev else None,
            "n_cards": len(out), "cards": out}


def region_activity(region: str, limit: int = 40) -> dict:
    """Cards/customers active in a billing region — supports out-of-region
    reasoning and region-based ring clustering (R6)."""
    res = _q(f'''
    INTERPRET QUERY () FOR GRAPH FraudInvestigation {{
      S = {{BillingRegion.*}};
      T = SELECT t FROM S:r -(BILLED_IN_reverse:e)- Transaction:t
          WHERE r.region == "{region}" LIMIT {int(limit)};
      C = SELECT c FROM T:t -(MADE_reverse:e)- Card:c;
      PRINT C;
    }}''')
    cards = _attrs(res[0]["C"]) if res and res[0]["C"] else []
    seen, out = set(), []
    for c in cards:
        if c["card_id"] in seen:
            continue
        seen.add(c["card_id"])
        out.append({"card_id": c["card_id"], "customer_id": c["customer_id"]})
    return {"region": region, "n_cards": len(out), "cards": out}


def connected_cards(card_id: str) -> dict:
    """Cards linked to this card by a shared device profile (the strongest
    cross-customer link). Feeds connected_card_ids, MONITOR_CONNECTED_CARDS (R6),
    and the BLOCK_ALL_CARDS bar (R10)."""
    res = _q(f'''
    INTERPRET QUERY () FOR GRAPH FraudInvestigation {{
      S = {{Card.*}};
      MY = SELECT t FROM S:c -(MADE:e)- Transaction:t WHERE c.card_id == "{card_id}";
      DEV = SELECT d FROM MY:t -(FROM_DEVICE:e)- DeviceProfile:d;
      OT = SELECT t2 FROM DEV:d -(FROM_DEVICE_reverse:e)- Transaction:t2;
      OC = SELECT c2 FROM OT:t2 -(MADE_reverse:e)- Card:c2 WHERE c2.card_id != "{card_id}";
      PRINT DEV, OC;
    }}''')
    devs = _attrs(res[0]["DEV"]) if res and res[0]["DEV"] else []
    cards = _attrs(res[0]["OC"]) if res and res[0]["OC"] else []
    seen, out = set(), []
    for c in cards:
        if c["card_id"] in seen:
            continue
        seen.add(c["card_id"])
        out.append({"card_id": c["card_id"], "customer_id": c["customer_id"]})
    return {"card_id": card_id,
            "shared_devices": [d["device_id"] for d in devs],
            "n_connected": len(out), "connected_cards": out}


# placeholder-tools-3


@lru_cache(maxsize=1)
def _txn_cache() -> dict[str, dict]:
    """Pruned transaction rows from the cached extract, keyed by txn_id
    (data/exam_txns.csv). ADR-0004: richer per-txn features live in the CSV, not
    the graph; this is the on-demand fetch path without rescanning the 676MB
    source."""
    out: dict[str, dict] = {}
    p = DATA / "exam_txns.csv"
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["TransactionID"]] = r
    return out


@lru_cache(maxsize=1)
def _identity_cache() -> dict[str, dict]:
    out: dict[str, dict] = {}
    p = DATA / "exam_identity.csv"
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["TransactionID"]] = r
    return out


def transaction_features(txn_id: str) -> dict:
    """Full available features for one transaction from the CSV cache: amount,
    region, purchaser/recipient email, product, channel, risk_score, and the
    joined device profile (type, info, OS, browser, new-device flag)."""
    t = _txn_cache().get(txn_id)
    if not t:
        return {"txn_id": txn_id, "found": False}
    idr = _identity_cache().get(txn_id, {})
    return {
        "txn_id": txn_id, "found": True,
        "amount": float(t["TransactionAmt"] or 0),
        "product_cd": t["ProductCD"], "channel": t["channel"],
        "risk_score": (float(t["risk_score"]) if t["risk_score"] else None),
        "region": t["addr1"], "addr2": t["addr2"],
        "p_email": t["P_emaildomain"], "r_email": t["R_emaildomain"],
        "ts": t["ts"], "customer_id": t["customer_id"],
        "device": {"type": idr.get("DeviceType", ""), "info": idr.get("DeviceInfo", ""),
                   "os": idr.get("id_30", ""), "browser": idr.get("id_31", ""),
                   "screen": idr.get("id_33", ""), "is_new": idr.get("id_15", "")},
    }


def similar_closed_cases(pattern: str = "", exposure_usd: float = 0.0,
                         top_k: int = 5) -> dict:
    """Retrieve resolved closed-case precedents from graph memory (ClosedCase),
    filtered by pattern when given and ranked by nearest exposure. Feeds
    similar_prior_cases and grounds the verdict in how the bank resolved like
    cases before. Memory is label-blind of the held-out eval (disjoint by
    customer), so a precedent can never be the answer itself."""
    where = f'WHERE cc.pattern == "{pattern}"' if pattern else ""
    res = _q(f'''
    INTERPRET QUERY () FOR GRAPH FraudInvestigation {{
      S = {{ClosedCase.*}};
      R = SELECT cc FROM S:cc {where} LIMIT 400;
      PRINT R;
    }}''')
    rows = _attrs(res[0]["R"]) if res and res[0]["R"] else []
    rows.sort(key=lambda r: abs(float(r.get("exposure_usd") or 0) - exposure_usd))
    out = [{"case_id": r["case_id"], "outcome": r["outcome"], "pattern": r["pattern"],
            "exposure_usd": r["exposure_usd"], "report_filed": r["report_filed"],
            "analyst_notes": (r.get("analyst_notes") or "")[:280]}
           for r in rows[:top_k]]
    return {"pattern": pattern or "any", "matched": len(rows),
            "returned": len(out), "cases": out}


# tool registry (name -> callable) for the P3 function-calling loop
GRAPH_TOOLS = {
    "card_for_txn": card_for_txn,
    "card_txn_history": card_txn_history,
    "card_window": card_window,
    "device_neighbors": device_neighbors,
    "region_activity": region_activity,
    "connected_cards": connected_cards,
    "transaction_features": transaction_features,
    "similar_closed_cases": similar_closed_cases,
}


if __name__ == "__main__":
    import json
    print("card_for_txn:", card_for_txn("3514030"))
    print("device_neighbors:", json.dumps(device_neighbors("3478561"), indent=2)[:600])
    print("connected_cards:", json.dumps(connected_cards("C13487-K1"), indent=2)[:600])
    print("transaction_features:", json.dumps(transaction_features("3514030"), indent=2))
    print("similar_closed_cases:", json.dumps(
        similar_closed_cases("card_testing", 268.0, 3), indent=2)[:700])




