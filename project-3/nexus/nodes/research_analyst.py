"""Node 1 — Research Analyst (Ava): a bounded ReAct agent (D-017).

Baseline tools run in code; then Think → Act → Observe → Remember repeats until the policy submits
or the 8-call cap is hit; submit_dossier validates and grounds the result (one repair attempt, D-012).
The loop, caps and telemetry are identical for the scripted and Claude policies.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from nexus import explain, llm
from nexus.data import provider
from nexus.policies import RESEARCH_TOOLS, Action, ResearchContext, format_result, make_research_policy
from nexus.schemas import AgentStep, HandoffSummary, ResearchDossier, ToolResult
from nexus.state import MAX_AGENT_TOOL_CALLS, FundGraphState
from nexus.telemetry import clip, emit, emit_agent_started, micro_action, now_iso, record_handoff, ref
from nexus.tools import registry
from nexus.tools.research import GroundingError

AGENT = "research_analyst"
BASELINE = ("sec_get_financials", "get_valuation", "get_price_history", "compute_technicals")
FOLLOW_UPS = {t["name"] for t in RESEARCH_TOOLS} - {"submit_dossier"}
MAX_THINK_STEPS = MAX_AGENT_TOOL_CALLS + 4  # room to submit (and repair once) after the last tool call
MAX_SUBMITS = 2  # first attempt + one repair (D-012)


def _signal(score: float) -> str:
    if score >= 8:
        return f"STRONG BULLISH ({score:.1f}/10)"
    if score >= 6.5:
        return f"BULLISH ({score:.1f}/10)"
    if score >= 5:
        return f"NEUTRAL ({score:.1f}/10)"
    return f"BEARISH ({score:.1f}/10)"


def _handoff(d: ResearchDossier, follow_ups: int) -> HandoffSummary:
    action = "consider a core long sized within the single-name cap" if d.conviction_score >= 6.5 else "hold unless the risk/reward improves"
    return HandoffSummary(
        signal=_signal(d.conviction_score),
        opinion=f"PM should {action}.",
        why_rationale=clip(
            f"Scorecard {d.scorecard.base_score:.1f} adjusted {d.llm_adjustment:+.1f} after {follow_ups} follow-up check{'' if follow_ups == 1 else 's'}: "
            f"{d.bull_case.split(';')[0].rstrip('.')}; but {d.bear_case[0].lower()}{d.bear_case[1:]}", 400),
    )


class _Thoughts:
    """Streams Ava's summarized reasoning as `agent_thought` events, throttled for the UI."""

    def __init__(self, run_id: str) -> None:
        self.run_id, self.buf, self.last = run_id, "", 0.0

    def __call__(self, delta: str) -> None:
        self.buf += delta
        if time.monotonic() - self.last > 0.4:
            self.last = time.monotonic()
            emit({"type": "agent_thought", "run_id": self.run_id, "agent_id": AGENT, "text": self.buf[-600:], "partial": True})

    def flush(self) -> None:
        if self.buf:
            emit({"type": "agent_thought", "run_id": self.run_id, "agent_id": AGENT, "text": self.buf[-600:], "partial": False})
        self.buf = ""


def _think_text(a: Action, steps: int) -> str:
    if a.kind == "tool":
        return f"→ {registry.get_spec(AGENT, a.tool).code} {a.tool}: {a.reason}"
    if a.kind == "submit":
        return "→ done: enough evidence to write the dossier"
    return f"→ stop: {a.message}"


def research_analyst(state: FundGraphState) -> dict[str, Any]:
    run, ticker = state.run_id, state.ticker
    round_no = state.research_rounds + 1
    started = now_iso()
    emit_agent_started(run, AGENT, f"round {round_no}: PM asked \"{state.pm_question}\"" if state.pm_question else "")

    baseline: dict[str, ToolResult] = {}
    if round_no == 1:
        for name in BASELINE:
            baseline[name] = registry.use(run, AGENT, name, ticker=ticker)
        baseline["compute_scorecard"] = registry.use(
            run, AGENT, "compute_scorecard",
            financials=baseline["sec_get_financials"].data, valuation=baseline["get_valuation"].data, technicals=baseline["compute_technicals"].data,
        )

    thoughts = _Thoughts(run)
    policy = make_research_policy(ticker, round_no, state.pm_question, on_thinking=thoughts)
    previous = state.dossier if round_no > 1 else None
    policy.begin(ResearchContext(run_id=run, ticker=ticker, company=provider().company(ticker), as_of=provider().as_of(),
                                 round_no=round_no, baseline=baseline, question=state.pm_question, previous=previous))

    results: dict[str, ToolResult] = dict(baseline)
    if previous is not None:
        results["previous_dossier"] = ToolResult(tool="previous_dossier", source="state", as_of=provider().as_of(), data=previous.model_dump(), evidence=previous.bull_case + " " + previous.bear_case)
    steps: list[AgentStep] = []
    dossier: ResearchDossier | None = None
    error, submits = "", 0

    for _ in range(MAX_THINK_STEPS):
        with micro_action(run, AGENT, "agent_think", "Think · choosing next step") as ev:
            action = policy.next_action()
            thoughts.flush()
            if action.kind == "tool" and len(steps) >= MAX_AGENT_TOOL_CALLS:
                ev.text = f"→ stop: tool-call cap reached ({MAX_AGENT_TOOL_CALLS}/{MAX_AGENT_TOOL_CALLS}); asking for the dossier"
            else:
                ev.text = _think_text(action, len(steps))

        if action.kind == "stop":
            error = action.message
            break

        if action.kind == "tool":
            if len(steps) >= MAX_AGENT_TOOL_CALLS:
                policy.observe(f"Tool-call limit ({MAX_AGENT_TOOL_CALLS}) reached. Call submit_dossier now with what you have.", is_error=True)
                continue
            if action.tool not in FOLLOW_UPS:
                policy.observe(f"Tool {action.tool!r} is not available. Use one of: {', '.join(sorted(FOLLOW_UPS))}.", is_error=True)
                continue
            try:
                result = registry.use(run, AGENT, action.tool, ticker=ticker, **action.args)
            except Exception as exc:  # a data source failing is reported back to the agent, not fatal
                policy.observe(f"Tool failed: {type(exc).__name__}: {exc}", is_error=True)
                continue
            key = action.tool if action.tool not in results else f"{action.tool}#{len(steps) + 1}"
            results[key] = result
            with micro_action(run, AGENT, "memory_write", "Remember · writing to run memory") as ev:
                steps.append(AgentStep(step=len(steps) + 1, tool=action.tool, args=action.args, reason=action.reason, evidence=result.evidence))
                ev.text = f"{len(steps)}/{MAX_AGENT_TOOL_CALLS} tool calls used"
            policy.observe(format_result(result))
            continue

        # submit: schema + grounding, one repair attempt (D-012)
        submits += 1
        label = "Submitting dossier (schema + grounding check)" if submits == 1 else "Repairing dossier after failed check"
        try:
            with micro_action(run, AGENT, "submit_dossier", f"SUBMIT · {label}") as ev:
                dossier = registry.call(AGENT, "submit_dossier", ticker=ticker, results=results, synthesis=action.synthesis, trace=steps, previous=previous)
                ev.text = f"Conviction {dossier.conviction_score:.1f} = base {dossier.scorecard.base_score:.1f} {dossier.llm_adjustment:+.1f} | {len(steps)} follow-up call{'' if len(steps) == 1 else 's'} | all numbers grounded"
            break
        except (GroundingError, ValidationError, KeyError) as exc:
            error = str(exc).splitlines()[0]
            if submits >= MAX_SUBMITS:
                break
            policy.reject(error)
    else:
        error = error or f"no dossier after {MAX_THINK_STEPS} steps"

    seq = len(state.handoff_log) + 1
    consumed = [ref(AGENT, previous)] if previous else []
    llm_fields = _llm_fields(policy)
    if dossier is None:
        record = record_handoff(
            run_id=run, seq=seq, agent_id=AGENT, status="FAILED", started_at=started, consumed=consumed, **llm_fields,
            handoff=HandoffSummary(signal="RESEARCH FAILED", opinion="PM should HOLD; the dossier could not be validated.", why_rationale=(error or "unknown error")[:400]),
        )
        return {"dossier": None, "research_rounds": round_no, "pm_question": None, "agent_trace": steps, "handoff_log": [record]}

    record = record_handoff(
        run_id=run, seq=seq, agent_id=AGENT, status="COMPLETED", started_at=started, consumed=consumed, **llm_fields,
        output=dossier, handoff=_handoff(dossier, len(dossier.agent_trace)), plain=explain.research(dossier),
    )
    return {"dossier": dossier, "research_rounds": round_no, "pm_question": None, "agent_trace": steps, "handoff_log": [record]}


def _llm_fields(policy: Any) -> dict[str, Any]:
    u = policy.usage
    fields = {"prompt_version": policy.prompt_version, "model": ", ".join(sorted(u.models)) if u and u.models else policy.model}
    if u is None:
        return fields
    return fields | {"tokens": u.tokens, "latency_ms": u.latency_ms, "llm_calls": u.calls, "input_tokens": u.input_tokens,
                     "output_tokens": u.output_tokens, "cache_read_tokens": u.cache_read_tokens,
                     "cache_write_tokens": u.cache_write_tokens, "cost_usd": round(llm.cost_usd(u), 6)}
