"""Pass 2 of the load: build the FraudInvestigation subgraph from the cached
extract (data/exam_txns.csv + data/exam_identity.csv) and upsert via pyTigerGraph.

Card identity (documented interp — the dataset hides the real card_id split):
fingerprint = (card1, card4, card6) = issuer + network + type. The flagged
transaction of each exam case anchors its GIVEN card_id to a fingerprint; a
customer's other fingerprints get an internal `-KD{n}` id that we never emit in
answers (README: "every ID in your answer files must exist in this dataset", so
answers only ever cite case_pack / closed_case card_ids).
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from dotenv import dotenv_values

from src.tg import connect

DATA = Path("data")


def _fp(row: dict) -> tuple[str, str, str]:
    return (row["card1"], row["card4"], row["card6"])


def _device_id(idr: dict) -> str:
    parts = [idr.get("DeviceInfo", ""), idr.get("id_30", ""), idr.get("id_31", ""), idr.get("id_33", "")]
    key = "|".join(p.strip() for p in parts).strip("|")
    return key or ""


def load_extract() -> tuple[list[dict], dict[str, dict]]:
    with open(DATA / "exam_txns.csv", newline="", encoding="utf-8") as f:
        txns = list(csv.DictReader(f))
    identity: dict[str, dict] = {}
    with open(DATA / "exam_identity.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            identity[r["TransactionID"]] = r
    return txns, identity


def anchors(dataset: Path) -> dict[str, str]:
    """flagged_txn_id -> given card_id, from the case pack."""
    with open(dataset / "case_pack.csv", newline="", encoding="utf-8") as f:
        return {r["flagged_txn_id"]: r["card_id"] for r in csv.DictReader(f)}


def assign_cards(txns: list[dict], flag_anchor: dict[str, str]) -> dict[str, str]:
    """txn_id -> card_id. Anchor each customer's fingerprints to given card_ids;
    label the rest internally."""
    by_cust: dict[str, list[dict]] = defaultdict(list)
    for t in txns:
        by_cust[t["customer_id"]].append(t)
    txn_card: dict[str, str] = {}
    for cust, rows in by_cust.items():
        # fingerprint -> given card_id (via any flagged txn in this fingerprint)
        fp_to_card: dict[tuple, str] = {}
        for t in rows:
            if t["TransactionID"] in flag_anchor:
                fp_to_card[_fp(t)] = flag_anchor[t["TransactionID"]]
        # order remaining fingerprints deterministically for internal labels
        fps = sorted({_fp(t) for t in rows}, key=lambda fp: min(
            int(t["TransactionID"]) for t in rows if _fp(t) == fp))
        n = 0
        for fp in fps:
            if fp not in fp_to_card:
                n += 1
                fp_to_card[fp] = f"{cust}-KD{n}"
        for t in rows:
            txn_card[t["TransactionID"]] = fp_to_card[_fp(t)]
    return txn_card


def build_and_upsert() -> None:
    e = dotenv_values(".env")
    dataset = Path(e["DATASET_DIR"])
    txns, identity = load_extract()
    txn_card = assign_cards(txns, anchors(dataset))
    build_graph(txns, identity, txn_card)


def build_graph(txns: list[dict], identity: dict[str, dict],
                txn_card: dict[str, str]) -> None:
    """Turn resolved (txn, identity, card) rows into vertices/edges and upsert.

    Reusable across passes: the exam load (build_and_upsert) and the held-out /
    ring load (load_heldout_txns.py) both funnel through here so the graph is
    built identically for every customer set. Idempotent upserts (empty-attr
    Customer/Region/Email merges never clobber existing attrs)."""
    customers: set[str] = set()
    cards: dict[str, dict] = {}
    regions: set[str] = set()
    emails: set[str] = set()
    devices: dict[str, dict] = {}
    txn_v: list[tuple] = []
    e_owns: set[tuple] = set()
    e_made: list[tuple] = []
    e_billed: list[tuple] = []
    e_email: list[tuple] = []
    e_device: list[tuple] = []

    for t in txns:
        tid = t["TransactionID"]
        cust = t["customer_id"]
        card = txn_card[tid]
        customers.add(cust)
        cards.setdefault(card, {"customer_id": cust, "issuer": t["card1"],
                               "network": t["card4"], "card_type": t["card6"]})
        e_owns.add((cust, card))
        amt = float(t["TransactionAmt"] or 0)
        rsk = float(t["risk_score"]) if t["risk_score"] not in ("", None) else -1.0
        txn_v.append((tid, {"amount": amt, "ts": t["ts"], "dt": int(t["TransactionDT"] or 0),
                            "channel": t["channel"], "product_cd": t["ProductCD"],
                            "risk_score": rsk, "addr1": t["addr1"],
                            "p_email": t["P_emaildomain"], "r_email": t["R_emaildomain"]}))
        e_made.append((card, tid))
        if t["addr1"]:
            regions.add(t["addr1"]); e_billed.append((tid, t["addr1"]))
        if t["P_emaildomain"]:
            emails.add(t["P_emaildomain"]); e_email.append((tid, t["P_emaildomain"]))
        idr = identity.get(tid)
        if idr:
            did = _device_id(idr)
            if did:
                devices.setdefault(did, {"device_type": idr.get("DeviceType", ""),
                    "device_info": idr.get("DeviceInfo", ""), "os": idr.get("id_30", ""),
                    "browser": idr.get("id_31", ""), "screen": idr.get("id_33", ""),
                    "is_new": idr.get("id_15", "")})
                e_device.append((tid, did))

    # NEXT edges: consecutive txns within a card, ordered by (dt, txn_id)
    by_card: dict[str, list[str]] = defaultdict(list)
    for card, tid in e_made:
        by_card[card].append(tid)
    dt_of = {t["TransactionID"]: int(t["TransactionDT"] or 0) for t in txns}
    e_next: list[tuple] = []
    for card, ids in by_card.items():
        ids.sort(key=lambda x: (dt_of[x], int(x)))
        e_next += [(ids[i], ids[i + 1]) for i in range(len(ids) - 1)]

    _upsert(customers, cards, txn_v, regions, emails, devices,
            e_owns, e_made, e_billed, e_email, e_device, e_next)


def _chunk(seq, n=5000):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _upsert(customers, cards, txn_v, regions, emails, devices,
            e_owns, e_made, e_billed, e_email, e_device, e_next) -> None:
    c = connect("FraudInvestigation")
    for b in _chunk(customers):
        c.upsertVertices("Customer", [(x, {}) for x in b])
    c.upsertVertices("Card", [(cid, a) for cid, a in cards.items()])
    for b in _chunk(txn_v):
        c.upsertVertices("Transaction", b)
    c.upsertVertices("BillingRegion", [(x, {}) for x in regions])
    c.upsertVertices("EmailDomain", [(x, {}) for x in emails])
    c.upsertVertices("DeviceProfile", [(d, a) for d, a in devices.items()])
    print(f"vertices: {len(customers)} Customer, {len(cards)} Card, {len(txn_v)} Transaction, "
          f"{len(regions)} Region, {len(emails)} Email, {len(devices)} Device")

    def push(src, etype, tgt, edges):
        for b in _chunk(edges):
            c.upsertEdges(src, etype, tgt, [(s, t, {}) for s, t in b])
    push("Customer", "OWNS", "Card", e_owns)
    push("Card", "MADE", "Transaction", e_made)
    push("Transaction", "BILLED_IN", "BillingRegion", e_billed)
    push("Transaction", "PURCHASER_EMAIL", "EmailDomain", e_email)
    push("Transaction", "FROM_DEVICE", "DeviceProfile", e_device)
    push("Transaction", "NEXT", "Transaction", e_next)
    print(f"edges: {len(e_owns)} OWNS, {len(e_made)} MADE, {len(e_billed)} BILLED_IN, "
          f"{len(e_email)} PURCHASER_EMAIL, {len(e_device)} FROM_DEVICE, {len(e_next)} NEXT")


if __name__ == "__main__":
    build_and_upsert()


