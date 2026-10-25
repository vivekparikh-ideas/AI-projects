"""Token/cost capture and LangSmith spans (D-044). Offline: the LangSmith client is a mock, Claude is a fake stream."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langsmith import traceable
from langsmith.run_helpers import tracing_context

from nexus import llm
from nexus.tools import registry


def _usage(input_tokens=100, output_tokens=50, read=0, write=0, split=None):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=read,
                           cache_creation_input_tokens=write, cache_creation=split)


@pytest.mark.parametrize("u, details", [
    (_usage(), None),
    (_usage(read=1000), {"cache_read": 1000}),
    (_usage(write=800), {"cache_creation": 800}),
    (_usage(read=10, write=800, split=SimpleNamespace(ephemeral_5m_input_tokens=800, ephemeral_1h_input_tokens=0)),
     {"cache_read": 10, "ephemeral_5m_input_tokens": 800}),
])
def test_usage_metadata_adds_cache_tokens_into_input(u, details):
    meta = llm.usage_metadata(u)
    cached = u.cache_read_input_tokens + u.cache_creation_input_tokens
    assert meta["input_tokens"] == 100 + cached
    assert meta["total_tokens"] == 150 + cached
    assert meta.get("input_token_details") == details


def test_cache_writes_are_priced_apart_from_input():
    u = llm.Usage()
    u.add(_usage(input_tokens=1_000_000, output_tokens=1_000_000, read=1_000_000, write=1_000_000), llm.MODEL)
    assert (u.input_tokens, u.cache_write_tokens, u.tokens) == (1_000_000, 1_000_000, 4_000_000)
    assert llm.cost_usd(u) == pytest.approx(4.00 + 20.00 + 0.20 + 5.00)


class _FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="thinking_delta", thinking="hmm"))

    def get_final_message(self):
        return self.message


def test_llm_span_carries_usage_cost_and_the_answering_model(monkeypatch):
    message = MagicMock(model="claude-fallback-x", stop_reason="end_turn", usage=_usage(read=1000))
    message.model_dump.return_value = {"content": []}
    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **_: _FakeStream(message))))
    monkeypatch.setattr(llm, "client", lambda: fake)
    ended = []
    messages = [{"role": "user", "content": "hi"}]
    with tracing_context(enabled=True, client=MagicMock()):
        llm.stream(system="s", messages=messages, usage=llm.Usage(), langsmith_extra={"on_end": ended.append})
    messages.append({"role": "assistant", "content": "later turn"})
    run = ended[0]
    meta = run.extra["metadata"]
    assert run.run_type == "llm" and meta["ls_model_name"] == "claude-fallback-x" and meta["fallback_used"] is True
    assert meta["usage_metadata"]["input_token_details"] == {"cache_read": 1000}
    assert meta["cost_usd"] == pytest.approx((100 * 4 + 50 * 20 + 1000 * 0.2) / 1e6)
    assert meta["first_token_ms"] is not None
    assert len(run.inputs["messages"]) == 1  # snapshot, not the list the policy keeps appending to
    assert "usage" not in run.inputs and "on_thinking" not in run.inputs


def test_registry_tool_calls_become_tool_spans(monkeypatch):
    name = next(iter(registry.REGISTRY["research_analyst"]))
    spec = registry.REGISTRY["research_analyst"][name]
    monkeypatch.setitem(registry.REGISTRY["research_analyst"], name, replace(spec, fn=lambda **kw: {"ok": kw}))
    ended = []

    @traceable(name="node")
    def node():
        return registry.call("research_analyst", name, ticker="NVDA")

    with tracing_context(enabled=True, client=MagicMock()):
        assert node(langsmith_extra={"on_end": ended.append}) == {"ok": {"ticker": "NVDA"}}
    tool = ended[0].child_runs[0]
    assert tool.run_type == "tool" and tool.name == name and tool.inputs == {"ticker": "NVDA"}
    assert tool.extra["metadata"]["agent_id"] == "research_analyst"


def test_handoff_record_carries_the_token_split_and_cost():
    from nexus.nodes.research_analyst import _llm_fields
    from nexus.telemetry import now_iso, record_handoff

    u = llm.Usage()
    u.add(_usage(read=1000, write=200), llm.MODEL)
    policy = SimpleNamespace(usage=u, prompt_version="research-v1", model=llm.MODEL)
    rec = record_handoff(run_id="run-1", seq=1, agent_id="research_analyst", status="FAILED", started_at=now_iso(), **_llm_fields(policy))
    assert (rec.llm_calls, rec.input_tokens, rec.cache_read_tokens, rec.cache_write_tokens, rec.tokens) == (1, 100, 1000, 200, 1350)
    assert rec.cost_usd == pytest.approx(llm.cost_usd(u))
