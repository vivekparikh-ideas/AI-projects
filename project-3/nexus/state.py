"""Shared LangGraph state. `handoff_log` is the single source of handoffs (D-015)."""

from __future__ import annotations

import operator
from typing import Annotated, Literal

from pydantic import BaseModel

from nexus.mock_data import MANDATE
from nexus.schemas import (
    AgentStep,
    ApprovalTicket,
    ExecutionReceipt,
    HandoffRecord,
    LedgerUpdate,
    PortfolioSnapshot,
    Recommendation,
    ResearchDossier,
    RiskCheckResult,
    RuleResult,
    TradeIntent,
)

MAX_RESEARCH_ROUNDS = 2  # first pass + one PM follow-up question (D-018)
MAX_RISK_REVISIONS = 1  # one resize after a resizable Risk Gate failure (D-018)
MAX_AGENT_TOOL_CALLS = 8  # research agent follow-up cap (D-017)
MAX_APPROVAL_RECHECKS = 2  # expired approvals that send the order back to The Vault (D-043)
APPROVAL_TTL_MIN = 15  # an approval ticket expires after 15 minutes... (D-013)
APPROVAL_MAX_DRIFT_PCT = 0.5  # ...or a 0.5% price move


class FundGraphState(BaseModel):
    run_id: str
    ticker: str
    fixture: str = "default"
    journey: Literal["evaluate", "research", "whatif"] = "evaluate"
    portfolio: PortfolioSnapshot | None = None  # None until the user sets up a fund (D-021)
    mandate: dict[str, float] = dict(MANDATE)

    dossier: ResearchDossier | None = None
    intent: TradeIntent | None = None
    recommendation: Recommendation | None = None
    risk: RiskCheckResult | None = None
    receipt: ExecutionReceipt | None = None
    ledger: LedgerUpdate | None = None

    handoff_log: Annotated[list[HandoffRecord], operator.add] = []
    agent_trace: Annotated[list[AgentStep], operator.add] = []

    # Bounded feedback loops (D-018)
    research_rounds: int = 0
    pm_attempts: int = 0
    risk_revisions: int = 0
    pm_question: str | None = None
    risk_feedback: list[RuleResult] | None = None

    pm_route: Literal["research", "risk", "hold"] | None = None
    risk_route: Literal["execute", "revise", "reject"] | None = None
    fund_route: Literal["risk", "awaiting_fund"] | None = None

    # Founder approval (D-043): the ticket the run paused on and what happened to it
    approval: ApprovalTicket | None = None
    approval_route: Literal["execute", "recheck", "rejected", "expired"] | None = None
    approval_rechecks: int = 0
