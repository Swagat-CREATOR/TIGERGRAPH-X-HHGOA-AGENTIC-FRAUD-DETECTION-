"""README-exact answer schema (strict Pydantic).

The emitted ``<case_id>.json`` must match the dataset README's Answer Format
field-for-field: *"Missing fields score zero for that part."* Every model here
uses ``extra="forbid"`` so a typo'd or stray field fails loudly at build time
rather than silently costing points.

Innovation extras (evidence-value scores, counterfactual action projections,
the structured tool trace) are NOT part of the graded answer — they live in the
separate ``CaseTrace`` sidecar so they can never perturb README-exact scoring.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

_STRICT = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Enums (values are the exact strings the README/answer key expect)
# --------------------------------------------------------------------------- #
class Verdict(str, Enum):
    fraud = "fraud"
    legitimate = "legitimate"
    uncertain = "uncertain"


class CaseStatus(str, Enum):
    open = "open"
    closed_fraud = "closed_fraud"
    closed_legitimate = "closed_legitimate"
    escalated = "escalated"


class Pattern(str, Enum):
    card_testing = "card_testing"
    card_not_present_fraud = "card_not_present_fraud"
    card_not_present_new_device = "card_not_present_new_device"
    out_of_region_use = "out_of_region_use"
    account_takeover = "account_takeover"
    undocumented = "undocumented"
    none = "none"


class EvidenceSource(str, Enum):
    graph = "graph"
    document = "document"
    customer = "customer"
    external = "external"


class EvidenceRequestType(str, Enum):
    customer_validation = "customer_validation"
    step_up_auth = "step_up_auth"
    analyst_info = "analyst_info"


class Action(str, Enum):
    ALLOW_TRANSACTION = "ALLOW_TRANSACTION"
    DECLINE_TRANSACTION = "DECLINE_TRANSACTION"
    MONITOR_CARD = "MONITOR_CARD"
    MONITOR_CONNECTED_CARDS = "MONITOR_CONNECTED_CARDS"
    WARN_CUSTOMER = "WARN_CUSTOMER"
    VERIFY_WITH_CUSTOMER = "VERIFY_WITH_CUSTOMER"
    STEP_UP_AUTH = "STEP_UP_AUTH"
    BLOCK_CARD = "BLOCK_CARD"
    BLOCK_ALL_CARDS = "BLOCK_ALL_CARDS"
    GENERATE_REPORT = "GENERATE_REPORT"
    CREATE_CASE = "CREATE_CASE"
    FILE_REPORT = "FILE_REPORT"
    ESCALATE_TO_ANALYST = "ESCALATE_TO_ANALYST"
    CLOSE_NO_FRAUD = "CLOSE_NO_FRAUD"


class Route(str, Enum):
    auto = "auto"
    L1 = "L1"
    L2 = "L2"


# --------------------------------------------------------------------------- #
# Answer format — top-level pieces
# --------------------------------------------------------------------------- #
class Evidence(BaseModel):
    model_config = _STRICT
    claim: str
    source: EvidenceSource
    ref: str  # query name, document section, or evidence_request id
    entity_ids: list[str] = Field(default_factory=list)


class EvidenceRequest(BaseModel):
    model_config = _STRICT
    type: EvidenceRequestType
    asked_after_step: int = Field(ge=0)
    assumed_response: str


class NBAItem(BaseModel):
    model_config = _STRICT
    action: Action
    route: Route
    reason: str  # must cite the policy rule (R1..R10 / §)


class NextBestActions(BaseModel):
    model_config = _STRICT
    initial: list[NBAItem]
    final: list[NBAItem]
    what_changed: str  # "nothing" when final == initial


class SAR(BaseModel):
    """Part 2. Always present; empty-valued when ``file`` is False (README rule)."""

    model_config = _STRICT
    file: bool
    reason: str
    narrative: str = ""
    subjects: list[str] = Field(default_factory=list)
    total_amount_usd: float = 0.0
    activity_dates: list[str] = Field(default_factory=list)  # [first, last] YYYY-MM-DD

    @model_validator(mode="after")
    def _shape(self) -> "SAR":
        if self.file:
            if not self.narrative.strip():
                raise ValueError("sar.narrative is required when file=true")
            if len(self.activity_dates) != 2:
                raise ValueError("sar.activity_dates must be [first, last] when file=true")
        else:
            if (
                self.narrative != ""
                or self.subjects
                or self.total_amount_usd != 0
                or self.activity_dates
            ):
                raise ValueError(
                    "when file=false: narrative='', subjects=[], "
                    "total_amount_usd=0, activity_dates=[]"
                )
        return self


class Case(BaseModel):
    """Part 1: the internal investigation record."""

    model_config = _STRICT
    status: CaseStatus
    verdict: Verdict
    fraud_probability: float = Field(ge=0.0, le=1.0)
    pattern: Pattern
    pattern_description: str = ""  # required iff pattern == undocumented
    affected_txn_ids: list[str] = Field(default_factory=list)
    first_suspicious_txn_id: str = ""
    connected_card_ids: list[str] = Field(default_factory=list)
    connected_device_profiles: list[str] = Field(default_factory=list)
    exposure_usd: float = 0.0
    evidence: list[Evidence] = Field(default_factory=list)
    similar_prior_cases: list[str] = Field(default_factory=list)
    summary: str
    written_to_graph: bool = False
    graph_case_id: str = ""

    @model_validator(mode="after")
    def _pattern_description_rule(self) -> "Case":
        undoc = self.pattern == Pattern.undocumented
        if undoc and not self.pattern_description.strip():
            raise ValueError("pattern_description is required when pattern=undocumented")
        if not undoc and self.pattern_description != "":
            raise ValueError('pattern_description must be "" unless pattern=undocumented')
        return self


class CaseAnswer(BaseModel):
    """The full ``<case_id>.json`` deliverable."""

    model_config = _STRICT
    case_id: str
    case: Case
    evidence_requests: list[EvidenceRequest] = Field(default_factory=list)
    next_best_actions: NextBestActions
    sar: SAR
    stop_reason: str
    tool_calls: int = Field(ge=0)
    tokens: int = Field(ge=0)
    latency_s: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _cross_field_rules(self) -> "CaseAnswer":
        # README Notes: a legitimate verdict carries no episode, no exposure, no SAR.
        if self.case.verdict == Verdict.legitimate:
            if self.case.affected_txn_ids:
                raise ValueError("legitimate verdict must have empty affected_txn_ids")
            if self.case.exposure_usd != 0:
                raise ValueError("legitimate verdict must have exposure_usd=0")
            if self.sar.file:
                raise ValueError("legitimate verdict cannot file a SAR")
        # sar.file must agree with FILE_REPORT appearing in the final actions.
        has_file_report = any(
            a.action == Action.FILE_REPORT for a in self.next_best_actions.final
        )
        if self.sar.file != has_file_report:
            raise ValueError(
                "sar.file must match presence of FILE_REPORT in next_best_actions.final"
            )
        return self

    def to_json(self) -> str:
        # Fields are defined in README order, so the emitted JSON reads in order.
        return self.model_dump_json(indent=2)


# --------------------------------------------------------------------------- #
# Innovation sidecar (NOT graded — kept out of <case_id>.json on purpose)
# --------------------------------------------------------------------------- #
class EvidenceValueCandidate(BaseModel):
    """One candidate evidence request the agent weighed (evidence-value reasoning)."""

    model_config = _STRICT
    type: EvidenceRequestType
    target_claim: str
    expected_decision_impact: float = Field(ge=0.0, le=1.0)  # expected shift in p
    rationale: str
    chosen: bool = False


class ActionProjection(BaseModel):
    """Counterfactual (stretch): the projected effect of one candidate action."""

    model_config = _STRICT
    action: Action
    projected_averted_exposure_usd: float = 0.0
    projected_customer_friction: str = "none"  # from README §1 impact column
    rationale: str = ""


class ToolCallRecord(BaseModel):
    """Structured per-call trace for observability (Codex ask)."""

    model_config = _STRICT
    step: int
    tool: str
    args: dict = Field(default_factory=dict)
    ok: bool = True
    error: str = ""
    result_summary: str = ""
    tokens: int = 0
    latency_s: float = 0.0


class CaseTrace(BaseModel):
    """Sidecar written to cases/<case_id>.trace.json + the graph + the UI."""

    model_config = _STRICT
    case_id: str
    model_version: str = ""
    snapshot_id: str = ""
    evidence_value: list[EvidenceValueCandidate] = Field(default_factory=list)
    action_projections: list[ActionProjection] = Field(default_factory=list)
    tool_trace: list[ToolCallRecord] = Field(default_factory=list)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

