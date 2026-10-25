import pytest

from nexus.tools import registry
from tests.conftest import run_pipeline


def test_llm_roles_hold_only_read_tools():
    for agent_id in registry.LLM_ROLES:
        perms = {s.name: s.permission for s in registry.REGISTRY[agent_id].values()}
        assert set(perms.values()) == {"read"}, perms


def test_irreversible_tools_live_only_in_execution():
    owners = {a for a, tools in registry.REGISTRY.items() for s in tools.values() if s.permission == "irreversible"}
    assert owners == {"execution_trader"}


def test_no_web_search_anywhere():
    names = {n for tools in registry.REGISTRY.values() for n in tools}
    assert not any("search" in n or "web" in n for n in names)


def test_unregistered_tool_is_refused():
    with pytest.raises(PermissionError):
        registry.call("research_analyst", "submit_limit_order")
    with pytest.raises(PermissionError):
        registry.call("portfolio_manager", "web_search")


def test_every_call_in_a_run_is_registered_for_its_role():
    run_pipeline("NVDA")
    assert registry.CALL_LOG, "no tool calls recorded"
    for agent_id, name in registry.CALL_LOG:
        assert name in registry.REGISTRY[agent_id]


def test_research_baseline_runs_in_fixed_order():
    run_pipeline("NVDA")
    research_calls = [n for a, n in registry.CALL_LOG if a == "research_analyst"]
    assert research_calls[:5] == ["sec_get_financials", "get_valuation", "get_price_history", "compute_technicals", "compute_scorecard"]
