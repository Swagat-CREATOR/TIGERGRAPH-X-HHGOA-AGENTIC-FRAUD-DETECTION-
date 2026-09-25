"""Pass 3 of the load: bring the 30 held-out eval customers' full transaction
histories into FraudInvestigation so P2/P3 can actually investigate the held-out
cases (evaluate.py). The exam load (Pass 1/2) only loaded the 20 case_pack
customers; the 30 held-out customers are DISJOINT from them (verified: 0 overlap),
so without this pass every held-out card is empty in the graph.

Only raw transactions/identity are loaded here. The eval LABELS (outcome,
pattern, report_filed, analyst_notes in data/heldout_eval.csv) are NEVER loaded
into the graph — they live only in that CSV and are read solely by evaluate.py
for scoring. The ClosedCase precedent memory (load_closed_cases.py) stays disjoint
by customer from these 30, so a pipeline can never retrieve the case it is solving.

Card identity mirrors load_exam: each held-out case's GIVEN card_id (from
heldout_eval.csv) anchors the fingerprint (card1,card4,card6) of its flagged txn
(first_fraud_txn_id, or txn_ids[0] for the label='none' cases with no fraud txn),
exactly the flagged txn evaluate.py presents. Everything then funnels through the
shared, idempotent load_exam.build_graph so the graph is built identically.

Usage:
  python -m src.load_heldout_txns            # extract (if needed) + upsert
  python -m src.load_heldout_txns --extract  # only rescan source -> data cache
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from dotenv import dotenv_values

from src.extract_subgraph import ID_KEEP, KEEP
from src.load_exam import assign_cards, build_graph

csv.field_size_limit(1 << 24)

DATA = Path("data")
TXNS = DATA / "heldout_txns.csv"
IDENT = DATA / "heldout_identity.csv"
def heldout_customers() -> set[str]:
    d = json.loads((DATA / "split_manifest.json").read_text(encoding="utf-8"))
    return set(d["heldout_customers"])


def heldout_anchors() -> dict[str, str]:
    """flagged_txn_id -> given card_id, from the held-out eval rows. The flagged
    txn is first_fraud_txn_id, else txn_ids[0] (the label='none' cases with no
    fraud txn) — the exact anchor evaluate.py presents to the pipelines."""
    anchors: dict[str, str] = {}
    with open(DATA / "heldout_eval.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            txn_ids = [t for t in (r.get("txn_ids") or "").split("|") if t]
            flagged = (r.get("first_fraud_txn_id") or "").strip() or (
                txn_ids[0] if txn_ids else "")
            card = (r.get("card_id") or "").strip()
            if flagged and card:
                anchors[flagged] = card
    return anchors


def extract(dataset: Path, targets: set[str]) -> None:
    """Stream the 676 MB transactions.csv + identity.csv ONCE, caching only the
    held-out customers' rows (pruned columns) — same shape as extract_subgraph."""
    txn_ids: set[str] = set()
    n = kept = 0
    with open(dataset / "transactions.csv", newline="", encoding="utf-8") as f, \
         open(TXNS, "w", newline="", encoding="utf-8") as w:
        r = csv.DictReader(f)
        wr = csv.DictWriter(w, fieldnames=KEEP)
        wr.writeheader()
        for row in r:
            n += 1
            if n % 100000 == 0:
                print(f"  scanned {n:,} rows, kept {kept:,}", file=sys.stderr)
            if row["customer_id"] in targets:
                wr.writerow({k: row[k] for k in KEEP})
                txn_ids.add(row["TransactionID"])
                kept += 1
    print(f"transactions: scanned {n:,}, kept {kept:,} for {len(targets)} customers")

    idn = 0
    with open(dataset / "identity.csv", newline="", encoding="utf-8") as f, \
         open(IDENT, "w", newline="", encoding="utf-8") as w:
        r = csv.DictReader(f)
        wr = csv.DictWriter(w, fieldnames=ID_KEEP)
        wr.writeheader()
        for row in r:
            if row["TransactionID"] in txn_ids:
                wr.writerow({k: row.get(k, "") for k in ID_KEEP})
                idn += 1
    print(f"identity: matched {idn:,} device rows")


def load_cache() -> tuple[list[dict], dict[str, dict]]:
    with open(TXNS, newline="", encoding="utf-8") as f:
        txns = list(csv.DictReader(f))
    identity: dict[str, dict] = {}
    with open(IDENT, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            identity[r["TransactionID"]] = r
    return txns, identity


def build_and_upsert(force_extract: bool = False) -> None:
    dataset = Path(dotenv_values(".env")["DATASET_DIR"])
    targets = heldout_customers()
    print(f"targets: {len(targets)} held-out customers")
    if force_extract or not (TXNS.exists() and IDENT.exists()):
        extract(dataset, targets)
    txns, identity = load_cache()
    txn_card = assign_cards(txns, heldout_anchors())
    build_graph(txns, identity, txn_card)


def main() -> None:
    ap = argparse.ArgumentParser(description="Load held-out eval customers into the graph.")
    ap.add_argument("--extract", action="store_true",
                    help="only rescan source -> data/heldout_txns.csv (no upsert)")
    args = ap.parse_args()
    if args.extract:
        dataset = Path(dotenv_values(".env")["DATASET_DIR"])
        targets = heldout_customers()
        print(f"targets: {len(targets)} held-out customers")
        extract(dataset, targets)
    else:
        build_and_upsert()


if __name__ == "__main__":
    main()

