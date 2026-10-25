from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from nexus.graph import build_graph, initial_state
from nexus.schemas import HandoffRecord
from nexus.tools import registry


@dataclass
class Run:
    custom: list[dict[str, Any]] = field(default_factory=list)
    final: dict[str, Any] = field(default_factory=dict)

    @property
    def records(self) -> list[HandoffRecord]:
        return self.final["handoff_log"]

    def by_agent(self, agent_id: str) -> list[HandoffRecord]:
        return [r for r in self.records if r.agent_id == agent_id]

    @property
    def micro_events(self) -> list[dict[str, Any]]:
        return [c["event"] for c in self.custom if c["type"] == "micro_action"]


def run_pipeline(ticker: str, fixture: str = "default", fund="sample") -> Run:
    run = Run()
    state = initial_state(ticker, fixture, fund)
    final: dict[str, Any] = {}
    for mode, chunk in build_graph().stream(state, config={"configurable": {"speed": 0, "approval": "auto"}}, stream_mode=["updates", "custom", "values"]):
        if mode == "custom":
            run.custom.append(chunk)
        elif mode == "values":
            final = chunk
    run.final = final
    return run


@pytest.fixture(autouse=True)
def _clear_call_log():
    registry.CALL_LOG.clear()
    yield
    registry.CALL_LOG.clear()
