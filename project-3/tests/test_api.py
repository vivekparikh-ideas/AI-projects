"""Hosted API (M2.5): offline on fixtures with a dev user and a temporary JSON store."""

import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA", "fixture")
    monkeypatch.setenv("NEXUS_POLICY", "scripted")
    monkeypatch.setenv("NEXUS_DEV_USER", "owner-1")
    monkeypatch.setenv("NEXUS_STORE_FILE", str(tmp_path / "store.json"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    import nexus.api.app as app_module

    app_module = importlib.reload(app_module)
    return TestClient(app_module.app), app_module


def _events(response) -> list[tuple[str, dict]]:
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_fund_round_trip(api):
    client, _ = api
    assert client.get("/api/fund").json() == {"fund": None}
    body = client.put("/api/fund", json={"cash": 100_000, "preset": "careful"}).json()
    assert body["snapshot"]["nav"] == 100_000 and body["mandate"]["max_single_name_pct"] == 3.0
    assert client.delete("/api/fund").json() == {"fund": None}


def test_advice_run_then_continue_with_cash(api):
    client, _ = api
    events = _events(client.post("/api/runs", json={"command": "Evaluate NVDA"}))
    kinds = [k for k, _ in events]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"
    finished = events[-1][1]
    assert finished["awaiting_fund"] and finished["outcome"].startswith("ADVICE: BUY about 4.2%")
    assert {"micro_action", "handoff_record", "agent_started"} <= set(kinds)

    cont = _events(client.post(f"/api/runs/{finished['run_id']}/continue", json={"cash": 100_000}))
    paused = cont[-1][1]
    assert paused["awaiting_approval"] and paused["outcome"].startswith("AWAITING YOUR APPROVAL · BUY")
    assert "execution_trader" not in {e.get("agent_id") for k, e in cont if k == "agent_started"}  # nothing simulated yet
    done = _events(client.post(f"/api/runs/{paused['run_id']}/approve", json={"decision": "approve"}))[-1][1]
    assert done["outcome"].startswith("FILLED & BOOKED") and not done["awaiting_fund"] and not done["awaiting_approval"]
    research = [e for k, e in cont if k == "agent_started" and e["agent_id"] == "research_analyst"]
    assert research == []  # continuing never repeats research
    assert client.get("/api/fund").json()["fund"]["cash"] == 100_000  # the typed cash became the fund

    history = client.get("/api/runs").json()["runs"]
    assert [r["parent_id"] for r in history] == [finished["run_id"], None]
    replay = client.get(f"/api/runs/{finished['run_id']}").json()
    assert replay["events"] and "final_state" not in replay


def test_whatif_and_research_journeys(api):
    client, _ = api
    assert client.post("/api/runs", json={"command": "Can I add $50k of AMD?"}).status_code == 422  # needs a fund
    client.put("/api/fund", json={"cash": 100_000})
    whatif = _events(client.post("/api/runs", json={"command": "Can I add $5k of NVDA?"}))
    assert whatif[-1][1]["outcome"].startswith("WHAT-IF: PASSES")
    research = _events(client.post("/api/runs", json={"command": "Research NVDA"}))
    assert research[-1][1]["outcome"].startswith("RESEARCH ONLY")


def test_bad_commands_are_rejected(api):
    client, _ = api
    assert client.post("/api/runs", json={"command": "tell me a joke"}).status_code == 422
    assert "Milestone 3" in client.post("/api/runs", json={"command": "Check my stocks"}).json()["detail"]
    assert client.post("/api/runs/nope/continue", json={"cash": 10}).status_code == 404


def test_requires_sign_in_without_dev_user(api, monkeypatch):
    _, app_module = api
    monkeypatch.setattr(app_module, "DEV_USER", None)
    client = TestClient(app_module.app)
    assert client.get("/api/fund").status_code == 401
    assert client.get("/api/health").status_code == 200


def _paused_run(client) -> dict:
    client.put("/api/fund", json={"cash": 100_000})
    finished = _events(client.post("/api/runs", json={"command": "Evaluate NVDA"}))
    kinds = [k for k, _ in finished]
    assert "awaiting_approval" in kinds
    ticket = next(e for k, e in finished if k == "awaiting_approval")["ticket"]
    assert ticket["action"] == "BUY" and ticket["shares"] > 0 and ticket["rules_passed"] == ticket["rules_total"]
    return finished[-1][1]


def test_reject_ends_without_a_trade(api):
    client, _ = api
    paused = _paused_run(client)
    events = _events(client.post(f"/api/runs/{paused['run_id']}/approve", json={"decision": "reject"}))
    assert events[-1][1]["outcome"] == "REJECTED BY YOU · nothing traded"
    assert "execution_trader" not in {e.get("agent_id") for k, e in events if k == "agent_started"}
    again = client.post(f"/api/runs/{paused['run_id']}/approve", json={"decision": "approve"})
    assert again.status_code == 409  # a decided ticket can't be approved later
    saved = client.get(f"/api/runs/{paused['run_id']}").json()
    assert not saved["awaiting_approval"] and any(e["type"] == "awaiting_approval" for e in saved["events"])  # one row, whole story


def test_expired_approval_goes_back_to_the_vault(api, monkeypatch):
    client, _ = api
    paused = _paused_run(client)
    from datetime import datetime, timedelta, timezone

    import nexus.nodes.approval as approval

    later = datetime.now(timezone.utc) + timedelta(minutes=16)
    monkeypatch.setattr(approval, "datetime", type("Clock", (datetime,), {"now": staticmethod(lambda tz=None: later)}))
    events = _events(client.post(f"/api/runs/{paused['run_id']}/approve", json={"decision": "approve"}))
    notes = [e["note"] for k, e in events if k == "agent_started" and e["agent_id"] == "risk_gate"]
    assert notes == ["fresh check: your approval expired"]
    assert events[-1][1]["awaiting_approval"]  # a fresh ticket waits for the user again
    assert "execution_trader" not in {e.get("agent_id") for k, e in events if k == "agent_started"}
