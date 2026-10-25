"""Early-exit step: mark roles the run never reached as SKIPPED (or AWAITING_FUND) so the record is complete."""

from __future__ import annotations

from typing import Any

from nexus.schemas import AGENT_ORDER
from nexus.state import FundGraphState
from nexus.telemetry import now_iso, record_handoff


def finalize(state: FundGraphState) -> dict[str, Any]:
    seen = {r.agent_id for r in state.handoff_log}
    status = "AWAITING_FUND" if state.fund_route == "awaiting_fund" else "SKIPPED"
    records = []
    for agent_id in AGENT_ORDER:
        if agent_id not in seen:
            records.append(record_handoff(
                run_id=state.run_id, seq=len(state.handoff_log) + len(records) + 1,
                agent_id=agent_id, status=status, started_at=now_iso(),
            ))
    return {"handoff_log": records}
