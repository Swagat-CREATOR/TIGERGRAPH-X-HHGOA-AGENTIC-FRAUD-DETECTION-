"""Knowledge-doc corpus for the GRIP GraphRAG layer.

The dataset README says plainly (Suggested graph schema): "Load the closed-case
narratives, this README's pattern section, the policy, and the regulatory
documents into TigerGraph vector search for retrieval." This module is that
corpus, expressed as GRIP Paper-shaped docs so ``graphrag_ingest`` can persist
them (see [[grip-doc-layer-native]]): each doc becomes a Paper vertex, its
``authors`` the source, and frequency extraction mints shared Concept vertices
(card testing, device profile, exposure, SAR, ...) that cross-link related docs.

Every fact here is copied from the README / Fraud Policy v1.0 or from policy.py
constants — no invented regulatory text, and NOTHING case-specific: these are
pattern/policy/SAR definitions, so there is zero exam-answer leakage. Closed-case
narratives (the ClosedCase memory layer) are ingested separately under the
label-blind held-out split, not here.

Doc id conventions (used as `ref` in answer evidence, e.g. "document:POLICY-R5"):
  POLICY-*   Fraud Policy sections and rules R1..R10
  PATTERN-*  the five known patterns + undocumented guidance
  SAR-*      SAR filing + narrative standard
"""
from __future__ import annotations

from . import policy


def _doc(doc_id: str, title: str, source: str, tags: list[str], body: str) -> dict:
    """A GRIP Paper-shaped knowledge doc. `abstract` carries the full text that
    local_search scans and provenance cites; `authors` records the source."""
    return {
        "id": doc_id,
        "title": title,
        "abstract": " ".join(body.split()),  # normalise whitespace
        "authors": [source],
        "categories": tags,
    }


# placeholder-corpus

# --------------------------------------------------------------------------- #
# The five known fraud patterns (README "The five known fraud patterns")
# --------------------------------------------------------------------------- #
PATTERNS = [
    _doc(
        "PATTERN-CARD-TESTING", "Card testing", "HHGOA README",
        ["pattern", "card_testing"],
        """A stolen card number is checked before use: three or more tiny online
        authorizations, often under $5, then a larger purchase. Confirmed by the
        sequence itself. Under policy R5, three or more small online
        authorizations on one card within an hour followed by a larger purchase
        warrant DECLINE_TRANSACTION and STEP_UP_AUTH; if a purchase over $100 has
        already cleared, recommend BLOCK_CARD. Pattern value: card_testing.""",
    ),
    _doc(
        "PATTERN-CNP-FRAUD", "Card-not-present fraud", "HHGOA README",
        ["pattern", "card_not_present_fraud"],
        """The number is used online without the card. Amounts and products that
        do not fit the cardholder's history, often in a burst of two to four
        within 48 hours. On its own, one unusual online purchase is ambiguous:
        verify before blocking (policy R1 to R4). Pattern value:
        card_not_present_fraud.""",
    ),
    _doc(
        "PATTERN-CNP-NEW-DEVICE", "Card-not-present fraud from a new device",
        "HHGOA README", ["pattern", "card_not_present_new_device"],
        """Same as card-not-present fraud, with the identity record marking the
        device as New for this account, sometimes behind a proxy. Stronger than
        plain card-not-present fraud, still not proof: people buy new phones.
        Weigh the New-device signal with history before blocking. Pattern value:
        card_not_present_new_device.""",
    ),
    _doc(
        "PATTERN-OUT-OF-REGION", "Out-of-region use", "HHGOA README",
        ["pattern", "out_of_region_use"],
        """Card-present purchases in a billing region the cardholder has no
        history in, while their normal activity continues at home. Several days
        of purchases in one new region is a trip, not a clone. Policy R2 and R3
        apply. Pattern value: out_of_region_use.""",
    ),
    _doc(
        "PATTERN-ACCOUNT-TAKEOVER", "Account takeover", "HHGOA README",
        ["pattern", "account_takeover"],
        """Mixed-channel activity inconsistent with the cardholder, often with
        device and match-flag anomalies, pointing to stolen credentials rather
        than a stolen number. Pattern value: account_takeover.""",
    ),
    _doc(
        "PATTERN-UNDOCUMENTED", "Undocumented patterns", "Fraud Policy v1.0",
        ["pattern", "undocumented", "R9"],
        """The five known patterns are not the only ones in the data. When
        activity fits none of them but the evidence shows coordinated or repeated
        abuse across customers, recommend CREATE_CASE, FILE_REPORT, and
        ESCALATE_TO_ANALYST (rule R9), and describe the pattern in your own words
        rather than forcing it into a known category. Pattern value: undocumented,
        with a required pattern_description.""",
    ),
]

# placeholder-policy

# --------------------------------------------------------------------------- #
# Fraud Policy v1.0 — overview + the ten rules (README "Fraud Policy")
# --------------------------------------------------------------------------- #
POLICY = [
    _doc(
        "POLICY-OVERVIEW", "Fraud Policy v1.0 — overview", "Fraud Policy v1.0",
        ["policy", "actions", "routing", "exposure", "stopping"],
        f"""Every transaction carries a risk_score between 0 and 1 from the
        bank's detection model; it is a reason to look, never a verdict. Actions
        the agent may recommend: ALLOW_TRANSACTION, DECLINE_TRANSACTION,
        MONITOR_CARD, MONITOR_CONNECTED_CARDS, WARN_CUSTOMER, VERIFY_WITH_CUSTOMER,
        STEP_UP_AUTH, BLOCK_CARD, BLOCK_ALL_CARDS, GENERATE_REPORT, CREATE_CASE,
        FILE_REPORT, ESCALATE_TO_ANALYST, CLOSE_NO_FRAUD. Approval routing: auto
        actions may be executed by the agent; DECLINE_TRANSACTION and BLOCK_CARD
        when exposure is at most ${policy.BLOCK_CARD_L2_EXPOSURE_USD:,.0f} need L1
        (team lead); BLOCK_CARD when exposure exceeds
        ${policy.BLOCK_CARD_L2_EXPOSURE_USD:,.0f}, BLOCK_ALL_CARDS always, and
        FILE_REPORT always need L2 (fraud manager). Exposure is the sum of the
        absolute amounts of every transaction identified as part of the fraud
        episode, including the flagged one, in USD. Stopping: stop when fraud
        probability is at or above {policy.STOP_CONFIDENT_HI} or at or below
        {policy.STOP_CONFIDENT_LO} with at least two independent pieces of
        evidence, when a verification response settles the question, or when
        further steps are unlikely to change the decision. Every recommendation
        must cite the rule number it follows.""",
    ),
    _doc(
        "POLICY-R1", "R1 — Verify before you block on a weak signal",
        "Fraud Policy v1.0", ["policy", "rule", "R1"],
        f"""If the case rests on a single signal (including a risk score alone)
        and assessed fraud probability is below {policy.VERIFY_MAX_P}, recommend
        VERIFY_WITH_CUSTOMER or STEP_UP_AUTH before any block. Blocking a
        legitimate customer on one signal is a policy breach.""",
    ),
    _doc(
        "POLICY-R2", "R2 — Customer denies the transaction", "Fraud Policy v1.0",
        ["policy", "rule", "R2"],
        f"""Recommend BLOCK_CARD and CREATE_CASE. Add FILE_REPORT if exposure
        exceeds ${policy.SAR_EXPOSURE_USD:,.0f} or the case connects to a shared
        device profile or another card's fraud.""",
    ),
    _doc(
        "POLICY-R3", "R3 — Customer confirms the transaction", "Fraud Policy v1.0",
        ["policy", "rule", "R3"],
        """Recommend CLOSE_NO_FRAUD. Note the confirmation in the case file.""",
    ),
    _doc(
        "POLICY-R4", "R4 — No reply within 24 hours", "Fraud Policy v1.0",
        ["policy", "rule", "R4"],
        f"""Recommend MONITOR_CARD and DECLINE_TRANSACTION for pending
        authorizations. Escalate if exposure exceeds
        ${policy.ESCALATE_EXPOSURE_USD:,.0f}.""",
    ),
    _doc(
        "POLICY-R5", "R5 — Card testing", "Fraud Policy v1.0",
        ["policy", "rule", "R5", "card_testing"],
        """Three or more small online authorizations on one card within an hour,
        followed by a larger purchase: recommend DECLINE_TRANSACTION and
        STEP_UP_AUTH. If a purchase over $100 has already cleared, recommend
        BLOCK_CARD.""",
    ),
    _doc(
        "POLICY-R6", "R6 — Shared origin", "Fraud Policy v1.0",
        ["policy", "rule", "R6", "ring"],
        """When several cards show fraud from the same device profile, the same
        billing region, or the same recipient email in one window, name the
        shared element, recommend CREATE_CASE and FILE_REPORT, and
        MONITOR_CONNECTED_CARDS for every card that shares it.""",
    ),
    _doc(
        "POLICY-R7", "R7 — Disputed but legitimate", "Fraud Policy v1.0",
        ["policy", "rule", "R7"],
        """When the customer disputes a charge that matches their own recurring
        pattern (same merchant, same amount, monthly), recommend CREATE_CASE,
        VERIFY_WITH_CUSTOMER, and WARN_CUSTOMER. Do not block.""",
    ),
    _doc(
        "POLICY-R8", "R8 — Escalate when uncertain and exposed",
        "Fraud Policy v1.0", ["policy", "rule", "R8"],
        f"""If the verdict is uncertain and exposure exceeds
        ${policy.ESCALATE_EXPOSURE_USD:,.0f}, or the evidence conflicts, recommend
        ESCALATE_TO_ANALYST.""",
    ),
    _doc(
        "POLICY-R9", "R9 — Undocumented patterns", "Fraud Policy v1.0",
        ["policy", "rule", "R9", "undocumented"],
        """When activity fits none of the known patterns but the evidence shows
        coordinated or repeated abuse across customers, recommend CREATE_CASE,
        FILE_REPORT, and ESCALATE_TO_ANALYST, and describe the pattern in your own
        words. Do not force it into a known category.""",
    ),
    _doc(
        "POLICY-R10", "R10 — Never BLOCK_ALL_CARDS lightly", "Fraud Policy v1.0",
        ["policy", "rule", "R10"],
        """Never recommend BLOCK_ALL_CARDS unless at least two of the customer's
        cards show confirmed fraud or the customer's credentials are confirmed
        compromised.""",
    ),
    _doc(
        "POLICY-3A-CASE-VS-SAR", "3a — A case is not a report", "Fraud Policy v1.0",
        ["policy", "case", "sar"],
        f"""A case (CREATE_CASE) is the bank's internal record of an
        investigation. Open one whenever fraud probability reaches
        {policy.CASE_CREATE_P}, whenever you request evidence, or whenever a
        customer disputes a charge; it can be closed as fraud or legitimate,
        updated as evidence arrives, and is written into the graph as case memory.
        A suspicious activity report (FILE_REPORT) is a regulatory filing sent
        outside the bank. A report always has a case behind it; most cases never
        need a report. Deciding correctly between case-only and case-plus-report
        is scored.""",
    ),
]

# placeholder-sar

# --------------------------------------------------------------------------- #
# SAR filing + narrative standard, and regulatory source pointers
# (README "Part 2: sar" and "Regulatory documents"). No invented regulatory
# text: the narrative standard is the README's own field spec, and REG-SOURCES
# lists only the source titles/URLs the README itself names.
# --------------------------------------------------------------------------- #
SAR = [
    _doc(
        "SAR-NARRATIVE-STANDARD", "SAR narrative standard", "Fraud Policy v1.0",
        ["sar", "narrative", "standard"],
        """A suspicious activity report is the regulatory filing, written so it
        stands on its own for a regulator who has none of the bank's context. The
        narrative must answer six questions: who (the customer, cards, merchants,
        and devices involved), what happened, when (the dates), where (locations
        and channels), how it was carried out, and why it is suspicious. Write six
        to twelve sentences. The subjects field lists the IDs of every customer,
        card, merchant, and device named in the narrative; total_amount_usd is the
        total of the suspicious activity; activity_dates is the first and last date
        of that activity as [first, last] in YYYY-MM-DD. The narrative is the one
        place in the answer to be complete — the case summary stays short. This
        standard follows FinCEN's SAR Narrative Guidance.""",
    ),
    _doc(
        "SAR-WHEN-TO-FILE", "When a SAR must be filed", "Fraud Policy v1.0",
        ["sar", "filing", "R2", "R6", "R9"],
        f"""File a suspicious activity report (FILE_REPORT) only when the policy
        calls for one; most cases never need it. A SAR is warranted for confirmed
        or strongly suspected fraud above threshold: exposure exceeding
        ${policy.SAR_EXPOSURE_USD:,.0f} when the customer denies the transaction
        (R2), or when several cards show fraud from a shared device profile,
        billing region, or recipient email in one window (R6, shared origin), or
        when coordinated or repeated abuse across customers fits no known pattern
        (R9, undocumented). The sar.file boolean must agree with whether
        FILE_REPORT appears in the final actions, and FILE_REPORT always routes to
        L2 (fraud manager). If file is false, narrative is empty, subjects and
        activity_dates are empty, and total_amount_usd is 0.""",
    ),
    _doc(
        "REG-SOURCES", "Regulatory sources on fraud typologies and SAR writing",
        "HHGOA README", ["regulatory", "reference", "fincen", "fatf"],
        """Authoritative public sources the README points to for fraud typologies,
        red flags, and how suspicious activity reports must be written. FinCEN (US
        Treasury): SAR Filing FAQs (October 2025); SAR Narrative Guidance, the
        standard for the sar.narrative; Preparing a Complete and Sufficient SAR
        Narrative; SAR Supporting Documentation (FIN-2007-G003); SAR Activity
        Review: Trends, Tips and Issues; Advisory on Account Takeover Activity;
        Advisory on Imposter Scams and Money Mule Schemes; Identity-Related
        Suspicious Activity (2021). FATF: Illicit Financial Flows from
        Cyber-Enabled Fraud; Money Laundering Using New Payment Methods. FFIEC BSA
        /AML Manual: Suspicious Activity Reporting. Cite these for provenance when
        an investigation turns on account takeover, identity fraud, money-mule, or
        SAR-writing standards.""",
    ),
]


# --------------------------------------------------------------------------- #
# Aggregator
# --------------------------------------------------------------------------- #
def docs() -> list[dict]:
    """The full knowledge-doc corpus (patterns + policy + SAR/regulatory) as
    GRIP Paper-shaped dicts, ready for ``graphrag_ingest``. Ordering is stable so
    ingest and provenance references are reproducible."""
    return [*PATTERNS, *POLICY, *SAR]


if __name__ == "__main__":
    corpus = docs()
    print(f"knowledge_docs corpus: {len(corpus)} docs")
    for d in corpus:
        print(f"  {d['id']:<26} {len(d['abstract']):>4} chars  {d['title']}")




