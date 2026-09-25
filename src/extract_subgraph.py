"""Pass 1 of the load: stream the 676 MB transactions.csv + identity.csv ONCE and
cache the targeted subgraph rows locally (pruned columns), so the loader can be
re-run without rescanning. ADR-0004: V / most C·D·M columns are dropped here;
transaction_features fetches them on demand later.

v1 scope = the 20 exam customers' full histories (needed to establish "normal"
and detect episodes). Ring-neighbours + eval set are added by a later pass.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from dotenv import dotenv_values

csv.field_size_limit(1 << 24)

KEEP = [
    "TransactionID", "TransactionDT", "TransactionAmt", "ProductCD",
    "card1", "card4", "card6", "addr1", "addr2",
    "P_emaildomain", "R_emaildomain", "customer_id", "ts", "channel", "risk_score",
]
ID_KEEP = ["TransactionID", "id_15", "id_30", "id_31", "id_33", "DeviceType", "DeviceInfo"]


def exam_customers(dataset: Path) -> set[str]:
    with open(dataset / "case_pack.csv", newline="", encoding="utf-8") as f:
        return {r["customer_id"] for r in csv.DictReader(f)}


def main() -> None:
    e = dotenv_values(".env")
    dataset = Path(e["DATASET_DIR"])
    out = Path("data")
    out.mkdir(exist_ok=True)

    targets = exam_customers(dataset)
    print(f"targets: {len(targets)} exam customers")

    txn_ids: set[str] = set()
    n = kept = 0
    with open(dataset / "transactions.csv", newline="", encoding="utf-8") as f, \
         open(out / "exam_txns.csv", "w", newline="", encoding="utf-8") as w:
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

    # identity join (device) — only rows for our kept txns
    idn = 0
    with open(dataset / "identity.csv", newline="", encoding="utf-8") as f, \
         open(out / "exam_identity.csv", "w", newline="", encoding="utf-8") as w:
        r = csv.DictReader(f)
        wr = csv.DictWriter(w, fieldnames=ID_KEEP)
        wr.writeheader()
        for row in r:
            if row["TransactionID"] in txn_ids:
                wr.writerow({k: row.get(k, "") for k in ID_KEEP})
                idn += 1
    print(f"identity: matched {idn:,} device rows")


if __name__ == "__main__":
    main()

