"""Load closed-case MEMORY into FraudInvestigation, with a label-blind held-out
eval split drawn DISJOINT BY CUSTOMER.

Why disjoint by customer (not just by case id): 16 of the 20 exam customers also
have closed cases in closed_cases_history.csv, and 753 history customers have
more than one case. If any of those cases were in memory, a pipeline solving a
case for customer X could retrieve X's own prior resolved case and read its
outcome/pattern/narrative straight off — leakage. So a customer is EITHER a
memory customer, OR an exam customer, OR a held-out eval customer; never two.

Three disjoint customer sets:
  * EXAM (20)      — the case_pack deliverable. Never in memory.
  * HELD-OUT (~30) — a stratified, deterministic sample of non-exam cases, one
                     case per customer, spread across patterns/outcomes. Labels
                     (outcome/pattern/exposure/report_filed) are kept in
                     data/heldout_eval.csv for SCORING ONLY and never reach any
                     pipeline. Used to measure P1 -> P2 -> P3 lift.
  * MEMORY (rest)  — every closed case whose customer is neither exam nor
                     held-out. Loaded as ClosedCase vertices so P3's
                     similar_closed_cases tool can retrieve precedents.

ClosedCase vertices are self-contained memory (outcome, pattern, exposure_usd,
n_txns, dates, report_filed, analyst_notes narrative). ON_CARD / CONNECTED_TO
upsert Card stubs so precedent connectivity is traversable; empty-attr upserts
merge and never clobber existing exam Card attributes.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from dotenv import dotenv_values

from src.tg import connect

DATA = Path("data")
N_HELDOUT_PER_PATTERN = 5   # x ~6 pattern buckets -> ~30 held-out cases
# patterns we stratify the held-out eval across (README's five + none + undoc)
PATTERNS = [
    "card_not_present_fraud", "out_of_region_use", "account_takeover",
    "card_not_present_new_device", "none", "undocumented",
]


def _read(dataset: Path) -> tuple[list[dict], set[str]]:
    with open(dataset / "closed_cases_history.csv", newline="", encoding="utf-8") as f:
        history = list(csv.DictReader(f))
    with open(dataset / "case_pack.csv", newline="", encoding="utf-8") as f:
        exam = {r["customer_id"] for r in csv.DictReader(f)}
    return history, exam


def choose_heldout(history: list[dict], exam: set[str]) -> tuple[list[dict], set[str]]:
    """Deterministic, stratified: for each pattern bucket take the first
    N_HELDOUT_PER_PATTERN cases (sorted by case_id) whose customer is non-exam
    and not already chosen. One case per customer."""
    by_pattern: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(history, key=lambda r: r["case_id"]):
        if r["customer_id"] not in exam:
            by_pattern[r["pattern"]].append(r)

    heldout: list[dict] = []
    chosen_cust: set[str] = set()
    for pat in PATTERNS:
        taken = 0
        for r in by_pattern.get(pat, []):
            if taken >= N_HELDOUT_PER_PATTERN:
                break
            if r["customer_id"] in chosen_cust:
                continue
            heldout.append(r)
            chosen_cust.add(r["customer_id"])
            taken += 1
    return heldout, chosen_cust


# placeholder-upsert


def _chunk(seq, n=5000):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _upsert_memory(memory: list[dict]) -> None:
    """Upsert ClosedCase memory vertices + ON_CARD / CONNECTED_TO edges (Card
    stubs). Empty-attr Card upserts merge, so exam Card attributes are safe."""
    c = connect("FraudInvestigation")

    cc_v: list[tuple] = []
    card_stubs: set[str] = set()
    on_card: list[tuple] = []
    connected: list[tuple] = []
    for r in memory:
        cid = r["case_id"]
        cc_v.append((cid, {
            "customer_id": r["customer_id"], "card_id": r["card_id"],
            "outcome": r["outcome"], "pattern": r["pattern"],
            "exposure_usd": float(r["exposure_usd"] or 0),
            "n_txns": int(r["n_txns"] or 0),
            "opened_at": r["opened_at"], "closed_at": r["closed_at"],
            "report_filed": r["report_filed"], "analyst_notes": r["analyst_notes"],
        }))
        if r["card_id"]:
            card_stubs.add(r["card_id"])
            on_card.append((cid, r["card_id"]))
        for cc in (r["connected_card_ids"] or "").split("|"):
            cc = cc.strip()
            if cc:
                card_stubs.add(cc)
                connected.append((cid, cc))

    for b in _chunk(cc_v):
        c.upsertVertices("ClosedCase", b)
    for b in _chunk(card_stubs):
        c.upsertVertices("Card", [(x, {}) for x in b])
    for b in _chunk(on_card):
        c.upsertEdges("ClosedCase", "ON_CARD", "Card", [(s, t, {}) for s, t in b])
    for b in _chunk(connected):
        c.upsertEdges("ClosedCase", "CONNECTED_TO", "Card", [(s, t, {}) for s, t in b])

    n = c.getVertexCount("ClosedCase")
    print(f"upserted {len(cc_v)} ClosedCase memory vertices "
          f"({len(on_card)} ON_CARD, {len(connected)} CONNECTED_TO); "
          f"backend ClosedCase count = {n}")


def main() -> None:
    e = dotenv_values(".env")
    dataset = Path(e["DATASET_DIR"])
    DATA.mkdir(exist_ok=True)
    history, exam = _read(dataset)

    heldout, heldout_cust = choose_heldout(history, exam)
    memory = [r for r in history
              if r["customer_id"] not in exam and r["customer_id"] not in heldout_cust]

    # Held-out eval set (labels retained — SCORING ONLY, never fed to pipelines).
    hcols = list(history[0].keys())
    with open(DATA / "heldout_eval.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=hcols)
        w.writeheader()
        w.writerows(heldout)

    manifest = {
        "exam_customers": len(exam),
        "heldout_cases": len(heldout),
        "heldout_customers": sorted(heldout_cust),
        "memory_cases": len(memory),
        "total_history": len(history),
        "heldout_by_pattern": {
            p: sum(1 for r in heldout if r["pattern"] == p) for p in PATTERNS
        },
    }
    (DATA / "split_manifest.json").write_text(json.dumps(manifest, indent=2))
    print("split:", json.dumps(manifest, indent=2))

    _upsert_memory(memory)


if __name__ == "__main__":
    main()

