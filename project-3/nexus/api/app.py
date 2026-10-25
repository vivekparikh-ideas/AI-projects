"""Nexus API for the hosted app (M2.5, D-036). Thin wrapper over the existing engine.

    POST /api/runs                 {"command": "Evaluate NVDA"} → Server-Sent Events for the whole run
    POST /api/runs/{id}/continue   {"cash": 100000} → continue an advice-only run at the PM (no re-research)
    POST /api/runs/{id}/approve    {"decision": "approve" | "reject"} → resume a run paused for approval (D-043)
    GET  /api/runs, /api/runs/{id} history (events included for replay)
    GET/PUT/DELETE /api/fund       the user's fund (cash, holdings, risk preset)

Every request needs a Supabase access token for an allowed email (single owner in M2.5).
Each run streams inside one request. A run paused for approval is saved by LangGraph's checkpointer
(Supabase Postgres in production, process memory locally) and resumed by the approve request.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from nexus import data, policies, store, tracing
from nexus.fund import FundConfig
from nexus.graph import build_graph, checkpoint_serde, initial_state, resume_with_fund, whatif_state
from nexus.render import summarize
from nexus.router import LATER, UnknownCommand, parse
from nexus.state import FundGraphState

app = FastAPI(title="Nexus API", docs_url=None, redoc_url=None)

# ── configuration (environment, set once per process) ────────────────────────
data.use(os.environ.get("NEXUS_DATA", "live"))
policies.set_mode(os.environ.get("NEXUS_POLICY", "claude"))  # type: ignore[arg-type]
STORE = store.from_env()
OWNER_EMAILS = {e.strip().lower() for e in os.environ.get("NEXUS_OWNER_EMAILS", "").split(",") if e.strip()}
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
DEV_USER = os.environ.get("NEXUS_DEV_USER") if not os.environ.get("VERCEL") else None  # never on Vercel


def _checkpointer():
    """Where a run paused for approval waits. Postgres survives cold starts; memory is for local dev and tests."""
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver(serde=checkpoint_serde())
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(dsn, min_size=0, max_size=4, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})
    saver = PostgresSaver(pool, serde=checkpoint_serde())
    saver.setup()  # creates the checkpoint tables once; later calls are no-ops
    return saver


CHECKPOINTER = _checkpointer()


def _config(run_id: str) -> dict[str, Any]:
    return {"configurable": {"speed": 0.0, "thread_id": run_id}, "recursion_limit": 40}

_token_cache: dict[str, tuple[float, str]] = {}


# ── auth ─────────────────────────────────────────────────────────────────────

def current_user(authorization: str | None = Header(default=None)) -> str:
    """Verify a Supabase access token with Supabase itself and allow only the owner's email."""
    if DEV_USER:
        return DEV_USER
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required")
    token = authorization.split(" ", 1)[1]
    cached = _token_cache.get(token)
    if cached and cached[0] > time.time():
        return cached[1]
    if not SUPABASE_URL or not OWNER_EMAILS:
        raise HTTPException(500, "Server auth is not configured")
    r = httpx.get(f"{SUPABASE_URL}/auth/v1/user", headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY}, timeout=10)
    if r.status_code != 200:
        raise HTTPException(401, "Session expired; sign in again")
    user = r.json()
    if (user.get("email") or "").lower() not in OWNER_EMAILS:
        raise HTTPException(403, "This Nexus is private")
    _token_cache[token] = (time.time() + 300, user["id"])
    return user["id"]


# ── fund ─────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "data": data.provider().name, "policy": policies.mode()}


@app.get("/api/me")
def me(user: str = Depends(current_user)) -> dict[str, Any]:
    return {"user_id": user}


@app.get("/api/fund")
def get_fund(user: str = Depends(current_user)) -> dict[str, Any]:
    fund = STORE.get_fund(user)
    if fund is None:
        return {"fund": None}
    snap = fund.snapshot()
    gross = sum(p.weight_pct for p in snap.positions)
    return {"fund": fund.model_dump(), "snapshot": {"nav": snap.nav, "cash": snap.settled_cash, "invested_pct": round(gross, 2), "positions": [p.model_dump() for p in snap.positions]}, "mandate": fund.mandate}


@app.put("/api/fund")
def put_fund(fund: FundConfig, user: str = Depends(current_user)) -> dict[str, Any]:
    STORE.put_fund(user, fund)
    return get_fund(user)


@app.delete("/api/fund")
def delete_fund(user: str = Depends(current_user)) -> dict[str, Any]:
    STORE.delete_fund(user)
    return {"fund": None}


# ── runs ─────────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    command: str = Field(min_length=1, max_length=200)


class ContinueRequest(BaseModel):
    cash: float = Field(gt=0, le=1e10)


class ApproveRequest(BaseModel):
    decision: Literal["approve", "reject"]


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def _stream_run(user: str, graph, run_input: Any, run_id: str, meta: dict[str, Any], prior_events: list[dict[str, Any]] | None = None) -> Iterator[str]:
    """Run (or resume) the graph inside the response, streaming every engine event. Save the run when it
    ends or pauses for approval; a resumed run keeps its earlier events so a replay shows the whole story."""
    try:
        yield from _run_events(user, graph, run_input, run_id, meta, prior_events)
    finally:
        tracing.flush()  # the function can freeze once the response ends; send queued traces first (D-044)


def _run_events(user: str, graph, run_input: Any, run_id: str, meta: dict[str, Any], prior_events: list[dict[str, Any]] | None) -> Iterator[str]:
    events: list[dict[str, Any]] = list(prior_events or [])
    config = _config(run_id) | tracing.run_config(
        run_id=run_id, journey=meta["journey"], ticker=meta["ticker"], thread_id=meta.get("parent_id") or run_id, user=user,
        parent_id=meta.get("parent_id"), tags=[policies.mode(), *(["resumed"] if meta.get("resumed") else [])])
    yield _sse("run_started", meta)
    try:
        # durability="exit": one checkpoint write when the run pauses or ends, not one per step
        for chunk in graph.stream(run_input, config=config, stream_mode="custom", durability="exit"):
            if chunk.get("type") != "agent_thought" or not chunk.get("partial"):
                events.append(chunk)  # partial thoughts stream live but are not stored
            yield _sse(chunk["type"], chunk)
    except Exception as exc:  # report to the client; the run is still saved below
        events.append({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
    snap = graph.get_state(config)
    if not snap.values:
        return
    final_state = FundGraphState(**snap.values)
    ticket = final_state.approval if snap.interrupts else None
    if ticket is not None:
        pause = {"type": "awaiting_approval", "run_id": run_id, "ticket": ticket.model_dump()}
        events.append(pause)
        yield _sse("awaiting_approval", pause)
    awaiting = final_state.fund_route == "awaiting_fund"
    outcome = summarize(final_state.handoff_log, final_state.approval_route, ticket)
    STORE.save_run(user, {**meta, "id": run_id, "outcome": outcome, "awaiting_fund": awaiting, "awaiting_approval": ticket is not None,
                          "events": events, "final_state": final_state.model_dump(mode="json")})
    yield _sse("run_finished", {"run_id": run_id, "outcome": outcome, "awaiting_fund": awaiting,
                                "awaiting_approval": ticket is not None, "ticket": ticket.model_dump() if ticket else None})


def _streaming(it: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(it, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/runs")
def start_run(req: RunRequest, user: str = Depends(current_user)) -> StreamingResponse:
    try:
        journey = parse(req.command)
    except UnknownCommand as exc:
        raise HTTPException(422, str(exc)) from None
    if journey.kind in LATER:
        raise HTTPException(422, LATER[journey.kind])
    fund = STORE.get_fund(user)
    try:
        if journey.kind == "whatif":
            if fund is None:
                raise HTTPException(422, "A what-if needs your fund. Add your cash first.")
            state, entry = whatif_state(journey.ticker, journey.amount, fund), "risk_gate"
        else:
            state, entry = initial_state(journey.ticker, fund=fund, journey=journey.kind), "research_analyst"
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc.args[0])) from None
    meta = {"command": req.command, "journey": journey.kind, "ticker": state.ticker, "parent_id": None, "entry": entry,
            "fund": None if state.portfolio is None else {"nav": state.portfolio.nav, "cash": state.portfolio.settled_cash}}
    return _streaming(_stream_run(user, build_graph(entry=entry, checkpointer=CHECKPOINTER), state, state.run_id, meta))


@app.post("/api/runs/{run_id}/continue")
def continue_run(run_id: str, req: ContinueRequest, user: str = Depends(current_user)) -> StreamingResponse:
    saved = STORE.get_run(user, run_id)
    if saved is None:
        raise HTTPException(404, "Run not found")
    if not saved["awaiting_fund"]:
        raise HTTPException(409, "This run is not waiting for a fund")
    fund = STORE.get_fund(user) or FundConfig(cash=req.cash)
    if fund.cash != req.cash:
        fund = fund.model_copy(update={"cash": req.cash})
    STORE.put_fund(user, fund)  # the cash the user just typed becomes their fund
    final = FundGraphState.model_validate(saved["final_state"])
    resumed = resume_with_fund(dict(final), fund)
    resumed = resumed.model_copy(update={"run_id": f"run-{uuid.uuid4().hex[:8]}"})  # its own row; parent_id links back
    meta = {"command": saved["command"], "journey": saved["journey"], "ticker": saved["ticker"], "parent_id": run_id, "entry": "portfolio_manager",
            "fund": {"nav": resumed.portfolio.nav, "cash": resumed.portfolio.settled_cash}}
    return _streaming(_stream_run(user, build_graph(entry="portfolio_manager", checkpointer=CHECKPOINTER), resumed, resumed.run_id, meta))


@app.post("/api/runs/{run_id}/approve")
def approve_run(run_id: str, req: ApproveRequest, user: str = Depends(current_user)) -> StreamingResponse:
    """Resume a run paused at "Your call". Approval checks expiry and price drift inside the graph."""
    saved = STORE.get_run(user, run_id)
    if saved is None:
        raise HTTPException(404, "Run not found")
    if not saved.get("awaiting_approval"):
        raise HTTPException(409, "This run is not waiting for your approval")
    graph = build_graph(entry=saved.get("entry") or "research_analyst", checkpointer=CHECKPOINTER)
    if not graph.get_state(_config(run_id)).interrupts:
        raise HTTPException(410, "This approval is no longer available (the server restarted). Run the evaluation again.")
    meta = {k: saved.get(k) for k in ("command", "journey", "ticker", "parent_id", "entry")} | {"fund": saved.get("fund"), "resumed": True}
    return _streaming(_stream_run(user, graph, Command(resume={"decision": req.decision}), run_id, meta, saved["events"]))


@app.get("/api/runs")
def list_runs(user: str = Depends(current_user)) -> dict[str, Any]:
    return {"runs": STORE.list_runs(user)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, user: str = Depends(current_user)) -> dict[str, Any]:
    saved = STORE.get_run(user, run_id)
    if saved is None:
        raise HTTPException(404, "Run not found")
    return {k: v for k, v in saved.items() if k != "final_state"}
