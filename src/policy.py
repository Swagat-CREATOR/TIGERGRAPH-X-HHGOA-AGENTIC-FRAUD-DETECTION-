"""Fraud Policy v1.0 — constants and pure decision predicates.

A faithful, deterministic encoding of the README's Fraud Policy (sections 1–6)
and answer-format rules. No model calls, no I/O. The agent proposes actions;
``validator.py`` enforces them; both import this module so the policy lives in
exactly one place.

Values flagged ``(interp)`` are our stated reading of deliberately fuzzy wording
in the policy; they are documented in PLAN.md / CONTEXT.md so the choice is
auditable rather than hidden in code.
"""
from __future__ import annotations

from .schema import Action, Route, Verdict

# --------------------------------------------------------------------------- #
# Thresholds
# --------------------------------------------------------------------------- #
CASE_CREATE_P = 0.30              # §3a: open a case once fraud_probability >= 0.30
VERIFY_MAX_P = 0.70               # R1: single weak signal below this -> verify, don't block
STRONGLY_SUSPECTED_P = 0.70       # §3a SAR "strongly suspected" lower bound (interp)
STOP_CONFIDENT_HI = 0.85          # §6: stop when p >= 0.85 with >=2 independent evidence
STOP_CONFIDENT_LO = 0.15          # §6: stop when p <= 0.15 with >=2 independent evidence
SAR_EXPOSURE_USD = 1000.0         # §3a: "exposure exceeds $1,000" arm
BLOCK_CARD_L2_EXPOSURE_USD = 2500.0  # §2: BLOCK_CARD is L1 when exposure <= 2500 else L2
ESCALATE_EXPOSURE_USD = 500.0     # R4 / R8: "exposure exceeds $500" arm

# README §1 — customer impact per action. Drives the counterfactual friction
# projection (higher friction = costlier false positive).
CUSTOMER_IMPACT: dict[Action, str] = {
    Action.ALLOW_TRANSACTION: "none",
    Action.DECLINE_TRANSACTION: "low",
    Action.MONITOR_CARD: "none",
    Action.MONITOR_CONNECTED_CARDS: "none",
    Action.WARN_CUSTOMER: "none",
    Action.VERIFY_WITH_CUSTOMER: "low",
    Action.STEP_UP_AUTH: "low",
    Action.BLOCK_CARD: "high",
    Action.BLOCK_ALL_CARDS: "very high",
    Action.GENERATE_REPORT: "none",
    Action.CREATE_CASE: "none",
    Action.FILE_REPORT: "none",
    Action.ESCALATE_TO_ANALYST: "none",
    Action.CLOSE_NO_FRAUD: "none",
}

# README §2 — actions the agent may execute alone.
AUTO_ACTIONS: frozenset[Action] = frozenset(
    {
        Action.ALLOW_TRANSACTION,
        Action.MONITOR_CARD,
        Action.MONITOR_CONNECTED_CARDS,
        Action.WARN_CUSTOMER,
        Action.VERIFY_WITH_CUSTOMER,
        Action.STEP_UP_AUTH,
        Action.GENERATE_REPORT,
        Action.CREATE_CASE,
        Action.ESCALATE_TO_ANALYST,
        Action.CLOSE_NO_FRAUD,
    }
)


def required_route(action: Action, exposure_usd: float) -> Route:
    """README §2 approval routing, including the exposure-conditional BLOCK_CARD."""
    if action in AUTO_ACTIONS:
        return Route.auto
    if action == Action.DECLINE_TRANSACTION:
        return Route.L1
    if action == Action.BLOCK_CARD:
        return Route.L1 if exposure_usd <= BLOCK_CARD_L2_EXPOSURE_USD else Route.L2
    if action in (Action.BLOCK_ALL_CARDS, Action.FILE_REPORT):
        return Route.L2
    raise ValueError(f"no routing rule for action {action!r}")


def sar_required(
    *,
    verdict: Verdict,
    fraud_probability: float,
    exposure_usd: float,
    shared_link: bool,
    coordinated_or_undocumented: bool,
) -> tuple[bool, str]:
    """README §3a SAR predicate.

    File a report iff (fraud **confirmed** OR **strongly suspected**) AND at least
    one of: exposure > $1,000; the activity connects to a shared device profile /
    region cluster / another customer's fraud; the pattern is coordinated or
    undocumented (R9). Returns (should_file, reason citing the policy).
    """
    confirmed = verdict == Verdict.fraud
    strongly_suspected = fraud_probability >= STRONGLY_SUSPECTED_P
    if not (confirmed or strongly_suspected):
        return False, "No SAR (§3a): fraud is neither confirmed nor strongly suspected."

    arms: list[str] = []
    if exposure_usd > SAR_EXPOSURE_USD:
        arms.append(f"exposure ${exposure_usd:,.2f} exceeds $1,000")
    if shared_link:
        arms.append("activity connects to a shared device/region/another customer's fraud")
    if coordinated_or_undocumented:
        arms.append("pattern is coordinated or undocumented (R9)")

    if not arms:
        return False, (
            "No SAR (§3a): fraud (strongly) suspected but no threshold arm met "
            "(exposure <= $1,000, no shared link, not coordinated/undocumented)."
        )
    basis = "confirmed" if confirmed else "strongly suspected"
    return True, f"File SAR (§3a): fraud {basis} AND " + "; ".join(arms) + "."

