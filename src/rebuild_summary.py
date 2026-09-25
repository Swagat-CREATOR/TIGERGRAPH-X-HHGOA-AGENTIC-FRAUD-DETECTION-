"""Rebuild cases/_runs/summary.json from the per-case answer files already on
disk — NO LLM calls.

A targeted re-run (`run_cases --cases HHG-001`) rewrites summary.json for only
the cases it touched, clobbering the full-batch scoreboard. But every case's
graded answer is persisted at cases/_runs/<P>/<case_id>.json, so the summary is
fully reconstructable offline: reload each answer into CaseAnswer, re-run the
local policy validator for its violations, and re-aggregate exactly as
run_cases.run() does. This lets us recover the P1->P2->P3 comparison without
spending a single API token.

Usage:
  python -m src.rebuild_summary
"""
from __future__ import annotations

import json
from pathlib import Path

from src.schema import CaseAnswer
from src.validator import check

RUNS = Path("cases") / "_runs"
PIPES = ["P1", "P2", "P3"]


def _model_version() -> str:
    """Best-effort provider model label, from any trace sidecar (else unknown)."""
    for p in PIPES:
        for tr in sorted((RUNS / p).glob("*.trace.json")):
            try:
                mv = json.loads(tr.read_text(encoding="utf-8")).get("model_version")
                if mv:
                    return mv
            except (json.JSONDecodeError, OSError):
                continue
    return "unknown"


def _row(ans: CaseAnswer, case_id: str) -> dict:
    """Reconstruct the exact summary row run_cases.run() would have written."""
    return {
        "case_id": case_id, "verdict": ans.case.verdict.value,
        "pattern": ans.case.pattern.value, "p": ans.case.fraud_probability,
        "exposure": ans.case.exposure_usd, "sar": ans.sar.file,
        "final_actions": [n.action.value for n in ans.next_best_actions.final],
        "tool_calls": ans.tool_calls, "tokens": ans.tokens,
        "latency_s": round(ans.latency_s, 1),
        "violations": check(ans)}


def rebuild() -> dict:
    model = _model_version()
    n_cases = 0
    pipelines: dict = {}
    for p in PIPES:
        pdir = RUNS / p
        if not pdir.exists():
            continue
        files = sorted(f for f in pdir.glob("*.json")
                       if not f.name.endswith(".trace.json"))
        errs = sorted(pdir.glob("*.error.txt"))
        rows: list[dict] = []
        for f in files:
            ans = CaseAnswer(**json.loads(f.read_text(encoding="utf-8")))
            rows.append(_row(ans, f.stem))
        n_cases = max(n_cases, len(rows) + len(errs))
        clean = sum(1 for r in rows if not r["violations"])
        pipelines[p] = {
            "n_ok": len(rows), "n_clean": clean, "n_fail": len(errs),
            "tokens_total": sum(r["tokens"] for r in rows),
            "tool_calls_total": sum(r["tool_calls"] for r in rows),
            "latency_total_s": round(sum(r["latency_s"] for r in rows), 1),
            "verdicts": {v: sum(1 for r in rows if r["verdict"] == v)
                         for v in {r["verdict"] for r in rows}},
            "cases": rows,
            "failures": [{"case_id": e.stem.replace(".error", ""),
                          "error": e.read_text(encoding="utf-8")[:200]}
                         for e in errs]}
    summary = {"model": model, "n_cases": n_cases, "pipelines": pipelines}
    (RUNS / "summary.json").write_text(json.dumps(summary, indent=2),
                                       encoding="utf-8")
    return summary


def main() -> None:
    s = rebuild()
    print(f"model: {s['model']}  |  reconstructed from per-case files (no API)")
    print(f"\n{'pipe':<5}{'ok':>4}{'clean':>7}{'fail':>6}{'tokens':>10}"
          f"{'tools':>7}{'latency_s':>11}")
    for p, d in s["pipelines"].items():
        print(f"{p:<5}{d['n_ok']:>4}{d['n_clean']:>7}{d['n_fail']:>6}"
              f"{d['tokens_total']:>10}{d['tool_calls_total']:>7}"
              f"{d['latency_total_s']:>11}")
        print(f"      verdicts: {d['verdicts']}")


if __name__ == "__main__":
    main()

