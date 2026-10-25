"""Fund check (deterministic, no AI): The Vault needs a fund before it can run its rules (D-021).

With no fund, The Vault steps up and asks for one; with a fund, the Risk Gate confirms it as its first check.
"""

from __future__ import annotations

from typing import Any

from nexus.state import FundGraphState
from nexus.telemetry import emit_agent_started, micro_action


def fund_check(state: FundGraphState) -> dict[str, Any]:
    if state.portfolio is not None:
        return {"fund_route": "risk"}
    emit_agent_started(state.run_id, "risk_gate", "needs your fund")
    with micro_action(state.run_id, "risk_gate", "fund_check", "Fund check · do I know what you're working with?") as ev:
        ev.text = "No fund set: asking for your cash (or advice only)"
    return {"fund_route": "awaiting_fund"}
