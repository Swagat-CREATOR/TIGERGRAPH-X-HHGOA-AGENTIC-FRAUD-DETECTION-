"""Held-out evaluation: the P1 -> P2 -> P3 lift + token-efficiency scoreboard.

Runs the three pipelines over the (up to) 30 label-blind held-out cases
(data/heldout_eval.csv) and scores each against the withheld ground truth:
  * pattern      — exact match on the fraud pattern label
  * fraud        — verdict 'fraud' vs outcome 'confirmed_fraud' (precision/recall/F1)
  * report_filed — sar.file vs the recorded SAR decision

The eval CSV's LABELS (outcome / pattern / report_filed / analyst_notes) are used
ONLY here for scoring and are NEVER placed in a CaseInput, so no pipeline ever
sees them. Each held-out case is presented exactly like a case_pack case: a
neutral, label-free trigger plus the flagged transaction id. The split is disjoint
by customer, so a pipeline can never retrieve the case it is currently solving.

RESUMABLE / clobber-proof: every completed (pipeline, case) is persisted to
cases/_eval/raw/<P>/<case_id>.json and skipped on re-run; eval_report.json is
rebuilt from ALL raw files after every run. This lets a large eval be split
across several token-capped API keys — run a slice per key (--offset/--limit),
swap the key in .env between runs, and the partial results compose into one
report. The full 30x3 eval is ~1.84M tokens; size each slice to the key's budget.

Usage:
  python -m src.evaluate                       # all 3 pipelines, all held-out cases
  python -m src.evaluate --offset 0 --limit 8  # first 8 cases (one capped key)
  python -m src.evaluate --offset 8 --limit 8  # next 8 (after swapping the key)
  python -m src.evaluate --aggregate           # only rebuild the report (no API)
  python -m src.evaluate --pipelines P3        # one pipeline
  python -m src.evaluate --force               # re-run even if cached
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

from src.knowledge import KnowledgeIndex
from src.llm import make_llm
from src.pipelines import PIPELINES, CaseInput

EVAL_CSV = Path("data") / "heldout_eval.csv"
OUT = Path("cases") / "_eval"
RAW = OUT / "raw"
PIPES = ["P1", "P2", "P3"]
@dataclass
class HeldoutCase:
    case_in: CaseInput
    true_pattern: str
    true_fraud: bool          # outcome == confirmed_fraud
    true_report: bool         # report_filed == Yes


def load_heldout() -> list[HeldoutCase]:
    """Build label-free CaseInputs + the withheld labels kept separately."""
    rows: list[HeldoutCase] = []
    with open(EVAL_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            txn_ids = [t for t in (r.get("txn_ids") or "").split("|") if t]
            flagged = (r.get("first_fraud_txn_id") or "").strip() or (
                txn_ids[0] if txn_ids else "")
            # Neutral, label-free trigger — mirrors a case_pack risk_score trigger.
            case_in = CaseInput(
                case_id=r["case_id"], opened_at=r.get("opened_at", ""),
                trigger_type="risk_score",
                trigger_text="Transaction flagged by monitoring for review.",
                flagged_txn_id=flagged, card_id=r.get("card_id", ""),
                customer_id=r.get("customer_id", ""), risk_score="")
            rows.append(HeldoutCase(
                case_in=case_in,
                true_pattern=(r.get("pattern") or "").strip(),
                true_fraud=(r.get("outcome") or "").strip() == "confirmed_fraud",
                true_report=(r.get("report_filed") or "").strip().lower() == "yes"))
    return rows


def _prf(tp: int, fp: int, fn: int) -> dict:
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3)}
def aggregate() -> dict:
    """Rebuild eval_report.json from every persisted per-case result (no API).

    Composes across slices run on different keys: each pipeline's metrics are
    computed over whatever cases have completed so far, so the report always
    reflects the full accumulated held-out sample."""
    report: dict = {"model": "", "n": 0, "pipelines": {}}
    total_n = 0
    for p in PIPES:
        pdir = RAW / p
        if not pdir.exists():
            continue
        recs = [json.loads(f.read_text(encoding="utf-8"))
                for f in sorted(pdir.glob("*.json"))]
        if not recs:
            continue
        n = len(recs)
        total_n = max(total_n, n)
        pat_ok = sum(int(r["pred_pattern"] == r["true_pattern"]) for r in recs)
        sar_ok = sum(int(r["pred_sar"] == r["true_report"]) for r in recs)
        tp = sum(int(r["pred_fraud"] and r["true_fraud"]) for r in recs)
        fp = sum(int(r["pred_fraud"] and not r["true_fraud"]) for r in recs)
        fn_ = sum(int((not r["pred_fraud"]) and r["true_fraud"]) for r in recs)
        tn = sum(int((not r["pred_fraud"]) and not r["true_fraud"]) for r in recs)
        toks = sum(int(r.get("tokens", 0)) for r in recs)
        report["pipelines"][p] = {
            "n": n,
            "pattern_accuracy": round(pat_ok / n, 3),
            "fraud": {**_prf(tp, fp, fn_),
                      "accuracy": round((tp + tn) / n, 3),
                      "tp": tp, "fp": fp, "fn": fn_, "tn": tn},
            "report_accuracy": round(sar_ok / n, 3),
            "tokens_total": toks,
            "tokens_per_case": round(toks / n, 1),
            "per_case": recs}
    report["n"] = total_n
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "eval_report.json").write_text(json.dumps(report, indent=2),
                                          encoding="utf-8")
    print("\n=== held-out lift (cases/_eval/eval_report.json) ===")
    print(f"{'pipe':<5}{'n':>4}{'pattern':>9}{'fraudF1':>9}{'fraudAcc':>10}"
          f"{'reportAcc':>11}{'tok/case':>10}")
    for p, s in report["pipelines"].items():
        print(f"{p:<5}{s['n']:>4}{s['pattern_accuracy']:>9}{s['fraud']['f1']:>9}"
              f"{s['fraud']['accuracy']:>10}{s['report_accuracy']:>11}"
              f"{s['tokens_per_case']:>10}")
    return report
def score(pipelines: list[str], limit: int | None, offset: int,
          force: bool) -> dict:
    held = load_heldout()
    held = held[offset:(offset + limit) if limit else None]
    idx = KnowledgeIndex()
    print(f"knowledge backend: {idx.backend}", flush=True)
    llm = make_llm()
    print(f"provider model: {llm.model}  |  cases[{offset}:{offset + len(held)}] "
          f"({len(held)})  |  pipelines {pipelines}", flush=True)
    try:
        for p in pipelines:
            fn = PIPELINES[p]
            tok0 = llm.tokens
            done = skipped = failed = 0
            for h in held:
                raw_f = RAW / p / f"{h.case_in.case_id}.json"
                if raw_f.exists() and not force:
                    skipped += 1
                    continue
                try:
                    a = fn(h.case_in, llm, idx).answer
                    rec = {
                        "case_id": h.case_in.case_id,
                        "pred_pattern": a.case.pattern.value,
                        "true_pattern": h.true_pattern,
                        "pred_fraud": a.case.verdict.value == "fraud",
                        "true_fraud": h.true_fraud,
                        "pred_sar": a.sar.file, "true_report": h.true_report,
                        "tokens": a.tokens, "tool_calls": a.tool_calls}
                    raw_f.parent.mkdir(parents=True, exist_ok=True)
                    raw_f.write_text(json.dumps(rec, indent=2), encoding="utf-8")
                    done += 1
                    print(f"  {p} {h.case_in.case_id} "
                          f"pat[{'Y' if rec['pred_pattern'] == rec['true_pattern'] else 'n'}] "
                          f"fraud[{'Y' if rec['pred_fraud'] == rec['true_fraud'] else 'n'}] "
                          f"sar[{'Y' if rec['pred_sar'] == rec['true_report'] else 'n'}] "
                          f"tok={a.tokens}", flush=True)
                except Exception as ex:  # noqa: BLE001
                    failed += 1
                    print(f"  {p} {h.case_in.case_id} FAIL {type(ex).__name__}: "
                          f"{str(ex)[:120]}", flush=True)
            print(f"  [{p}] done={done} skipped={skipped} failed={failed} "
                  f"tokens_this_run={llm.tokens - tok0}", flush=True)
    finally:
        idx.close()
    return aggregate()


def main() -> None:
    ap = argparse.ArgumentParser(description="Score held-out cases across pipelines.")
    ap.add_argument("--pipelines", default="P1,P2,P3")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--force", action="store_true",
                    help="re-run cases even if a cached result exists")
    ap.add_argument("--aggregate", action="store_true",
                    help="only rebuild eval_report.json from cached results (no API)")
    args = ap.parse_args()
    if args.aggregate:
        aggregate()
        return
    pipelines = [p.strip() for p in args.pipelines.split(",") if p.strip()]
    for p in pipelines:
        if p not in PIPELINES:
            ap.error(f"unknown pipeline {p!r}; choose from {list(PIPELINES)}")
    score(pipelines, args.limit, args.offset, args.force)


if __name__ == "__main__":
    main()




