"""Policy-compliance checks, run before every emit + write-back.

Not a rules engine: a flat list of the checks that catch the ways an LLM answer
actually breaks Fraud Policy. schema.py already enforces structure and the hard
cross-field ties (sar.file <-> FILE_REPORT, legitimate => no exposure); this
adds policy semantics on top. Returns a list of violations; [] means compliant.
"""
from __future__ import annotations

from . import policy
from .schema import Action, CaseAnswer, Pattern, Verdict

_BLOCKS = {Action.BLOCK_CARD, Action.BLOCK_ALL_CARDS, Action.DECLINE_TRANSACTION}
_VERIFY = {Action.VERIFY_WITH_CUSTOMER, Action.STEP_UP_AUTH}


def check(a: CaseAnswer) -> list[str]:
    v: list[str] = []
    c = a.case
    initial = {n.action for n in a.next_best_actions.initial}
    final = {n.action for n in a.next_best_actions.final}

    # Routes must match the policy matrix (exposure-conditional for BLOCK_CARD).
    for nba in (*a.next_best_actions.initial, *a.next_best_actions.final):
        want = policy.required_route(nba.action, c.exposure_usd)
        if nba.route != want:
            v.append(f"route: {nba.action.value} is {nba.route.value}, policy wants {want.value}")

    # R1: never block on a single weak signal (p<0.70) without verifying first.
    if c.fraud_probability < policy.VERIFY_MAX_P and (initial & _BLOCKS) and not (initial & _VERIFY):
        v.append("R1: initial actions block on p<0.70 without VERIFY_WITH_CUSTOMER/STEP_UP_AUTH first")

    # §3a: a report always has a case behind it.
    if Action.FILE_REPORT in final and Action.CREATE_CASE not in final:
        v.append("§3a: FILE_REPORT without CREATE_CASE behind it")

    # R8: uncertain and exposed (>$500) must escalate.
    if (
        c.verdict == Verdict.uncertain
        and c.exposure_usd > policy.ESCALATE_EXPOSURE_USD
        and Action.ESCALATE_TO_ANALYST not in final
    ):
        v.append("R8: uncertain verdict with exposure>$500 must ESCALATE_TO_ANALYST")

    # R10: BLOCK_ALL_CARDS needs 2+ compromised cards or confirmed credential compromise.
    # ponytail: proxy — flagged card + >=1 connected == 2; account_takeover == creds compromised.
    if Action.BLOCK_ALL_CARDS in final and not (
        c.pattern == Pattern.account_takeover or len(c.connected_card_ids) >= 1
    ):
        v.append("R10: BLOCK_ALL_CARDS without 2+ compromised cards or confirmed credential compromise")

    # Trivial contradiction: an episode with no dollars.
    if c.affected_txn_ids and c.exposure_usd <= 0:
        v.append("exposure_usd must be >0 when affected_txn_ids is non-empty")

    return v


if __name__ == "__main__":
    from .schema import SAR, Case, NBAItem, NextBestActions

    good = CaseAnswer(
        case_id="HHG-017",
        case=Case(status="closed_fraud", verdict="fraud", fraud_probability=0.86,
                  pattern="card_testing", affected_txn_ids=["T1"],
                  first_suspicious_txn_id="T1", exposure_usd=268.43, summary="s",
                  written_to_graph=True, graph_case_id="G1"),
        next_best_actions=NextBestActions(
            initial=[NBAItem(action="VERIFY_WITH_CUSTOMER", route="auto", reason="R1")],
            final=[NBAItem(action="BLOCK_CARD", route="L1", reason="R2"),
                   NBAItem(action="CREATE_CASE", route="auto", reason="R2"),
                   NBAItem(action="FILE_REPORT", route="L2", reason="R2")],
            what_changed="denied"),
        sar=SAR(file=True, reason="R2", narrative="n", subjects=["C1"],
                total_amount_usd=268.43, activity_dates=["2016-11-14", "2016-11-14"]),
        stop_reason="settled", tool_calls=1, tokens=1, latency_s=1.0)
    assert check(good) == [], check(good)

    bad = good.model_copy(deep=True)
    bad.case.fraud_probability = 0.4
    bad.next_best_actions.initial = [NBAItem(action="BLOCK_CARD", route="L2", reason="x")]
    viols = check(bad)
    assert any("route" in x for x in viols) and any("R1" in x for x in viols), viols
    print("validator self-check OK")

