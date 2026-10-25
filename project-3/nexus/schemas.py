"""Pydantic v2 data contracts shared by every role (REQUIREMENTS §4)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentId = Literal[
    "research_analyst",
    "portfolio_manager",
    "risk_gate",
    "execution_trader",
    "portfolio_ledger",
]
AGENT_ORDER: tuple[AgentId, ...] = (
    "research_analyst",
    "portfolio_manager",
    "risk_gate",
    "execution_trader",
    "portfolio_ledger",
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ── Telemetry ────────────────────────────────────────────────────────────────


class MicroActionEvent(Contract):
    run_id: str
    agent_id: AgentId
    action_id: str
    action_label: str
    status: Literal["IN_PROGRESS", "COMPLETED", "FAILED"]
    evidence_snippet: str = ""
    timestamp: str
    source_label: str | None = None  # where the evidence came from, e.g. "10-Q filed 2026-08-26"
    source_url: str | None = None    # link to it (SEC EDGAR, Yahoo Finance); None for sample data


class HandoffSummary(Contract):
    signal: str = Field(min_length=1, max_length=60)
    opinion: str = Field(min_length=1, max_length=240)
    why_rationale: str = Field(min_length=1, max_length=400)


class PlainEnglish(Contract):
    """Display-only explanation; never read by a downstream role (D-007)."""

    headline: str = Field(min_length=1)
    what_it_means: str = Field(min_length=1)
    so_what: str = Field(min_length=1)


class ArtifactRef(Contract):
    agent_id: AgentId
    artifact_type: str
    sha: str = Field(pattern=r"^[0-9a-f]{8}$")


class HandoffRecord(Contract):
    run_id: str
    seq: int = Field(ge=1)
    agent_id: AgentId
    status: Literal["COMPLETED", "FAILED", "REJECTED", "SKIPPED", "AWAITING_FUND"]
    started_at: str
    completed_at: str
    duration_ms: int = Field(ge=0)
    consumed: list[ArtifactRef] = []
    produced: ArtifactRef | None = None
    output_type: str | None = None
    output: dict[str, Any] | None = None
    handoff: HandoffSummary | None = None
    plain: PlainEnglish | None = None
    trigger: Literal["pipeline", "solo"] = "pipeline"
    # Filled from M2 when an LLM is involved (D-015).
    prompt_version: str | None = None
    model: str | None = None
    tokens: int | None = None
    latency_ms: int | None = None
    # The split behind `tokens`, and what it cost (D-044).
    llm_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost_usd: float | None = None


# ── Research ─────────────────────────────────────────────────────────────────


class ToolResult(Contract):
    tool: str
    source: str
    as_of: str
    data: dict[str, Any]
    evidence: str
    source_label: str | None = None
    source_url: str | None = None


class Source(Contract):
    tool: str
    label: str
    url: str | None = None


class AgentStep(Contract):
    """One Think → Act → Observe → Remember turn of the research agent."""

    step: int = Field(ge=1)
    tool: str
    args: dict[str, Any] = {}
    reason: str
    evidence: str


class Valuation(Contract):
    fwd_pe: float | None
    ev_ebitda: float | None
    fcf_yield_pct: float | None


class Dilution(Contract):
    diluted_shares_b: float | None
    sbc_pct_rev: float | None
    buyback_usd_b: float | None
    net_share_change_pct: float | None


class Technicals(Contract):
    spot: float
    dma50: float
    dma200: float
    rsi14: float
    vwap: float


class Scorecard(Contract):
    growth: float
    trend: float
    valuation: float
    dilution: float
    base_score: float


class ResearchDossier(Contract):
    ticker: str
    bull_case: str
    bear_case: str
    valuation: Valuation
    dilution: Dilution
    technicals: Technicals
    revenue_growth_pct: float | None
    gross_margin_pct: float | None
    insider_summary: str
    institutional_summary: str
    notes: list[str] = []
    scorecard: Scorecard
    llm_adjustment: float = Field(ge=-1.5, le=1.5)
    adjustment_reason: str = Field(min_length=1)
    conviction_score: float = Field(ge=0, le=10)
    agent_trace: list[AgentStep] = []
    sources: list[Source] = []   # every document and feed the research used, with links (D-040)
    reading_summary: str = ""     # e.g. "3 SEC documents · 16 insider filings · 252 days of prices · 3 follow-up checks"

    @model_validator(mode="after")
    def _conviction_is_base_plus_adjustment(self) -> ResearchDossier:
        expected = round(self.scorecard.base_score + self.llm_adjustment, 1)
        if abs(self.conviction_score - expected) > 1e-9:
            raise ValueError(f"conviction_score {self.conviction_score} != base + adjustment {expected}")
        return self


# ── Portfolio ────────────────────────────────────────────────────────────────


class Position(Contract):
    ticker: str
    shares: float
    price: float
    weight_pct: float


class RealizedLoss(Contract):
    ticker: str
    date: str
    amount_usd: float


class TaxLot(Contract):
    lot_id: str
    ticker: str
    shares: int
    cost_basis: float
    acquired: str
    term: Literal["short_term", "long_term"]


class PortfolioSnapshot(Contract):
    as_of: str
    nav: float
    settled_cash: float
    beta: float
    current_var_pct: float
    positions: list[Position]
    realized_losses: list[RealizedLoss] = []
    tax_lots: list[TaxLot] = []

    def weight_of(self, ticker: str) -> float:
        return sum(p.weight_pct for p in self.positions if p.ticker == ticker)


class TradeIntent(Contract):
    action: Literal["BUY", "SELL", "HOLD"]
    ticker: str
    target_weight_pct: float = Field(ge=0, le=100)
    dollar_amount: float = Field(ge=0)
    shares: int = Field(ge=0)
    limit_price: float = Field(ge=0)
    stop_loss_price: float = Field(ge=0)
    rationale: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> TradeIntent:
        if self.action == "HOLD":
            if self.shares or self.dollar_amount:
                raise ValueError("HOLD must have zero shares and dollars")
            return self
        if self.shares <= 0:
            raise ValueError(f"{self.action} needs a positive share count")
        if abs(self.shares * self.limit_price - self.dollar_amount) > 0.01:
            raise ValueError("dollar_amount must equal shares × limit_price")
        if self.action == "BUY" and not self.stop_loss_price < self.limit_price:
            raise ValueError("BUY stop_loss_price must be below limit_price")
        return self


class Recommendation(Contract):
    """The PM's advice when no fund is set: a share of the fund, not shares or dollars (D-021)."""

    action: Literal["BUY", "SELL", "HOLD"]
    ticker: str
    target_weight_pct: float = Field(ge=0, le=100)
    limit_price: float = Field(ge=0)
    stop_loss_price: float = Field(ge=0)
    stop_loss_pct: float = Field(ge=0, le=100)
    rationale: str = ""


# ── Risk ─────────────────────────────────────────────────────────────────────


class RuleResult(Contract):
    name: Literal["concentration", "cash_and_margin", "wash_sale", "marginal_var"]
    passed: bool
    observed: float
    limit: float
    unit: str
    resizable: bool
    detail: str


class RiskCheckResult(Contract):
    rules: list[RuleResult]
    approved: bool
    hitl_status: Literal["NOT_REQUIRED", "AUTO_APPROVED_STUB", "PENDING", "APPROVED", "REJECTED"]  # AUTO_APPROVED_STUB: pre-D-043 saved runs only
    var_before_pct: float
    var_after_pct: float

    @property
    def passed_count(self) -> int:
        return sum(r.passed for r in self.rules)


class ApprovalTicket(Contract):
    """The exact order the user approves or rejects (D-043). Fixed when issued so a resume can't change it."""

    ticket_id: str
    ticker: str
    action: Literal["BUY", "SELL"]
    shares: int
    limit_price: float
    dollar_amount: float
    stop_loss_price: float
    target_weight_pct: float
    rules_passed: int
    rules_total: int
    var_after_pct: float
    var_limit_pct: float
    price_at_issue: float
    issued_at: str
    expires_at: str
    max_drift_pct: float
    summary: str


# ── Execution & ledger ───────────────────────────────────────────────────────


class FillSlice(Contract):
    seq: int
    shares: int
    price: float


class ExecutionReceipt(Contract):
    ticker: str
    side: Literal["BUY", "SELL"]
    client_order_id: str
    shares_requested: int
    shares_filled: int
    fill_pct: float
    bid: float
    ask: float
    spread_bps: float
    arrival_price: float
    avg_fill_price: float
    slippage_bps: float
    commissions: float
    notional: float
    slices: list[FillSlice]


class LedgerUpdate(Contract):
    ticker: str
    tax_lot: TaxLot
    broker_shares: int
    ledger_shares: int
    reconciled: bool
    cash_before: float
    cash_after: float
    nav_before: float
    nav_after: float
    mark_price: float
