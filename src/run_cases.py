"""Batch driver for the 20 case_pack cases.

Runs any subset of the three pipelines (P1/P2/P3) over any subset of cases and
emits, per case:
  * the graded README-exact answer  -> cases/_runs/<P>/<case_id>.json
  * the (non-graded) trace sidecar   -> cases/_runs/<P>/<case_id>.trace.json
P3 is the deliverable pipeline, so its answer + trace are ALSO written to the
top-level cases/<case_id>.json + cases/<case_id>.trace.json the README asks for.

A per-run cases/_runs/summary.json captures the efficiency comparison
(tokens / tool_calls / latency / clean-vs-violating) that backs the P1->P2->P3
lift story. Each case is isolated in try/except so one failure never kills the
batch; a failure writes <case_id>.error.txt and is counted in the summary.

Usage:
  python -m src.run_cases                      # all 3 pipelines, all 20 cases
  python -m src.run_cases --pipelines P3       # just the deliverable
  python -m src.run_cases --cases HHG-001,HHG-014
  python -m src.run_cases --limit 3            # first 3 cases (smoke)
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from src.knowledge import KnowledgeIndex
from src.llm import make_llm
from src.pipelines import PIPELINES, load_cases
from src.write_cases import write_case_to_graph

OUT = Path("cases")
RUNS = OUT / "_runs"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(pipelines: list[str], case_ids: set[str] | None) -> dict:
    cases = [c for c in load_cases()
             if case_ids is None or c.case_id in case_ids]
    idx = KnowledgeIndex()
    print(f"knowledge backend: {idx.backend}", flush=True)
    llm = make_llm()
    print(f"provider model: {llm.model}  |  {len(cases)} cases  |  "
          f"pipelines {pipelines}", flush=True)

    summary: dict = {"model": llm.model, "n_cases": len(cases), "pipelines": {}}
    # P3 is the deliverable: its cases are also written to the graph (spec
    # requirement). One connection, reused; if the graph is unreachable the run
    # still completes and the answers are simply flagged written_to_graph=false.
    case_conn = None
    if "P3" in pipelines:
        try:
            from src.tg import connect
            case_conn = connect("FraudInvestigation")
        except Exception as gex:  # noqa: BLE001
            print(f"[graph case write-back disabled: {type(gex).__name__}: "
                  f"{str(gex)[:80]}]", flush=True)
    try:
        for p in pipelines:
            fn = PIPELINES[p]
            rows: list[dict] = []
            fails: list[dict] = []
            tok0 = llm.tokens
            for c in cases:
                try:
                    res = fn(c, llm, idx)
                    a = res.answer
                    if p == "P3" and case_conn is not None:
                        # spec: "the case should also be written to the graph"
                        try:
                            gid = write_case_to_graph(case_conn, a)
                            a.case.written_to_graph = True
                            a.case.graph_case_id = gid
                        except Exception as gex:  # noqa: BLE001
                            print(f"    [graph write skipped {c.case_id}: "
                                  f"{type(gex).__name__}: {str(gex)[:80]}]", flush=True)
                    _write(RUNS / p / f"{c.case_id}.json", a.to_json())
                    _write(RUNS / p / f"{c.case_id}.trace.json", res.trace.to_json())
                    if p == "P3":  # the deliverable copy
                        _write(OUT / f"{c.case_id}.json", a.to_json())
                        _write(OUT / f"{c.case_id}.trace.json", res.trace.to_json())
                    rows.append({
                        "case_id": c.case_id, "verdict": a.case.verdict.value,
                        "pattern": a.case.pattern.value, "p": a.case.fraud_probability,
                        "exposure": a.case.exposure_usd, "sar": a.sar.file,
                        "final_actions": [n.action.value for n in a.next_best_actions.final],
                        "tool_calls": a.tool_calls, "tokens": a.tokens,
                        "latency_s": round(a.latency_s, 1),
                        "violations": res.violations})
                    flag = "OK  " if not res.violations else "VIOL"
                    print(f"  {p} {c.case_id} {flag} {a.case.verdict.value:<10} "
                          f"{a.case.pattern.value:<26} sar={int(a.sar.file)} "
                          f"tools={a.tool_calls} tok={a.tokens} "
                          f"{a.latency_s:5.1f}s", flush=True)
                except Exception as ex:  # noqa: BLE001
                    _write(RUNS / p / f"{c.case_id}.error.txt", f"{type(ex).__name__}: {ex}")
                    fails.append({"case_id": c.case_id,
                                  "error": f"{type(ex).__name__}: {str(ex)[:200]}"})
                    print(f"  {p} {c.case_id} FAIL {type(ex).__name__}: "
                          f"{str(ex)[:120]}", flush=True)
            clean = sum(1 for r in rows if not r["violations"])
            summary["pipelines"][p] = {
                "n_ok": len(rows), "n_clean": clean, "n_fail": len(fails),
                "tokens_total": llm.tokens - tok0,
                "tool_calls_total": sum(r["tool_calls"] for r in rows),
                "latency_total_s": round(sum(r["latency_s"] for r in rows), 1),
                "verdicts": {v: sum(1 for r in rows if r["verdict"] == v)
                             for v in {r["verdict"] for r in rows}},
                "cases": rows, "failures": fails}
    finally:
        idx.close()

    _write(RUNS / "summary.json", json.dumps(summary, indent=2))
    print("\n=== summary (cases/_runs/summary.json) ===")
    print(f"{'pipe':<5}{'ok':>4}{'clean':>7}{'fail':>6}{'tokens':>10}"
          f"{'tools':>7}{'latency_s':>11}")
    for p, s in summary["pipelines"].items():
        print(f"{p:<5}{s['n_ok']:>4}{s['n_clean']:>7}{s['n_fail']:>6}"
              f"{s['tokens_total']:>10}{s['tool_calls_total']:>7}"
              f"{s['latency_total_s']:>11}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Run case_pack cases through the pipelines.")
    ap.add_argument("--pipelines", default="P1,P2,P3",
                    help="comma-separated subset of P1,P2,P3")
    ap.add_argument("--cases", default=None,
                    help="comma-separated case_ids (default: all)")
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N cases (smoke runs)")
    args = ap.parse_args()

    pipelines = [p.strip() for p in args.pipelines.split(",") if p.strip()]
    for p in pipelines:
        if p not in PIPELINES:
            ap.error(f"unknown pipeline {p!r}; choose from {list(PIPELINES)}")

    case_ids: set[str] | None = None
    if args.cases:
        case_ids = {c.strip() for c in args.cases.split(",") if c.strip()}
    elif args.limit:
        case_ids = {c.case_id for c in load_cases()[: args.limit]}

    run(pipelines, case_ids)


if __name__ == "__main__":
    main()

