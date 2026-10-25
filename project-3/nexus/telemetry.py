"""Live micro-action telemetry and handoff records (REQUIREMENTS R-TEL-1..3)."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from langgraph.config import get_config, get_stream_writer
from pydantic import BaseModel

from nexus.schemas import (
    AgentId,
    ArtifactRef,
    HandoffRecord,
    HandoffSummary,
    MicroActionEvent,
    PlainEnglish,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha8(model: BaseModel) -> str:
    return hashlib.sha256(model.model_dump_json().encode()).hexdigest()[:8]


def ref(agent_id: AgentId, model: BaseModel) -> ArtifactRef:
    return ArtifactRef(agent_id=agent_id, artifact_type=type(model).__name__, sha=sha8(model))


def clip(text: str, limit: int) -> str:
    """Fit LLM-written text into a display contract field without cutting a word in half."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def emit(payload: dict[str, Any]) -> None:
    # Outside a graph run (unit tests of tools) there is no writer; drop silently.
    try:
        get_stream_writer()(payload)
    except RuntimeError:
        pass


def _speed() -> float:
    try:
        return float(get_config().get("configurable", {}).get("speed", 0.0))
    except RuntimeError:
        return 0.0


def emit_agent_started(run_id: str, agent_id: AgentId, note: str = "") -> None:
    emit({"type": "agent_started", "run_id": run_id, "agent_id": agent_id, "note": note})


class _Evidence:
    text: str = ""
    source_label: str | None = None
    source_url: str | None = None


@contextmanager
def micro_action(run_id: str, agent_id: AgentId, action_id: str, label: str) -> Iterator[_Evidence]:
    """Emit IN_PROGRESS, run the body, then COMPLETED with evidence (or FAILED and re-raise)."""

    def event(status: str, evidence: str = "", holder: _Evidence | None = None) -> dict[str, Any]:
        e = MicroActionEvent(
            source_label=holder.source_label if holder else None,
            source_url=holder.source_url if holder else None,
            run_id=run_id,
            agent_id=agent_id,
            action_id=action_id,
            action_label=label,
            status=status,
            evidence_snippet=evidence,
            timestamp=now_iso(),
        )
        return {"type": "micro_action", "event": e.model_dump()}

    emit(event("IN_PROGRESS"))
    time.sleep(_speed())
    holder = _Evidence()
    try:
        yield holder
    except Exception as exc:
        emit(event("FAILED", f"{type(exc).__name__}: {exc}"))
        raise
    emit(event("COMPLETED", holder.text, holder))


def record_handoff(
    *,
    run_id: str,
    seq: int,
    agent_id: AgentId,
    status: str,
    started_at: str,
    consumed: list[ArtifactRef] | None = None,
    output: BaseModel | None = None,
    handoff: HandoffSummary | None = None,
    plain: PlainEnglish | None = None,
    **llm: Any,
) -> HandoffRecord:
    """Build the role's HandoffRecord and stream it so the UI can pin it below the card. `llm` carries the
    LLM trace fields (prompt_version, model, tokens and their split, latency_ms, cost_usd; D-015, D-044)."""
    completed_at = now_iso()
    started = datetime.fromisoformat(started_at)
    record = HandoffRecord(
        run_id=run_id,
        seq=seq,
        agent_id=agent_id,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=int((datetime.fromisoformat(completed_at) - started).total_seconds() * 1000),
        consumed=consumed or [],
        produced=ref(agent_id, output) if output is not None else None,
        output_type=type(output).__name__ if output is not None else None,
        output=output.model_dump() if output is not None else None,
        handoff=handoff,
        plain=plain,
        **llm,
    )
    emit({"type": "handoff_record", "record": record.model_dump()})
    return record
