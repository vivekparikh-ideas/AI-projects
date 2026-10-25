"""Rich CLI renderer for the live stream: ⟳/✓/✗ checklist, then a Plain (default) or Pro handoff box."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from nexus.schemas import AGENT_ORDER, HandoffRecord

TITLES = {
    "research_analyst": "RESEARCH ANALYST · ReAct agent",
    "portfolio_manager": "PORTFOLIO MANAGER · LLM + sizing formula",
    "risk_gate": "RISK GATE · deterministic",
    "execution_trader": "EXECUTION TRADER · deterministic",
    "portfolio_ledger": "PORTFOLIO LEDGER · deterministic",
}


def _step(agent_id: str) -> str:
    return f"[{AGENT_ORDER.index(agent_id) + 1}/5]"


class Renderer:
    def __init__(self, console: Console | None = None, pro: bool = False) -> None:
        self.console = console or Console()
        self.pro = pro
        self.records: list[HandoffRecord] = []
        self._pending = False

    def handle(self, mode: str, chunk: Any) -> None:
        if mode != "custom":
            return
        kind = chunk.get("type")
        if kind == "agent_started":
            self._agent_started(chunk)
        elif kind == "micro_action":
            self._micro_action(chunk["event"])
        elif kind == "handoff_record":
            self._record(HandoffRecord(**chunk["record"]))
        elif kind == "agent_thought" and not chunk.get("partial"):
            self._thought(chunk["text"])

    def _agent_started(self, c: dict) -> None:
        note = f"  ({c['note']})" if c.get("note") else ""
        self.console.print()
        self.console.rule(Text(f"{_step(c['agent_id'])} {TITLES[c['agent_id']]}{note}", style="bold cyan"), align="left")

    def _micro_action(self, e: dict) -> None:
        aid, label, status, evidence = e["action_id"], e["action_label"], e["status"], e["evidence_snippet"]
        indent = "    " if aid in ("agent_think", "memory_write") else "  "
        live = self.console.is_terminal
        if status == "IN_PROGRESS":
            if live:
                self.console.print(Text(f"{indent}⟳ {label}…", style="yellow"), end="")
                self._pending = True
            return
        if self._pending:
            self.console.file.write("\r\033[2K")
            self._pending = False
        mark, style = ("✓", "green") if status == "COMPLETED" else ("✗", "bold red")
        if status == "COMPLETED" and evidence.startswith("FAIL ·"):
            mark, style = "✗", "red"
        if aid == "agent_think":
            style = "magenta"
        elif aid == "memory_write":
            style = "dim"
        line = Text(f"{indent}{mark} ", style=style)
        line.append(label, style="bold" if aid not in ("agent_think", "memory_write") else style)
        if evidence:
            line.append(f"  {evidence}", style="dim" if aid != "agent_think" else "magenta")
        self.console.print(line)

    def _thought(self, text: str) -> None:
        line = " ".join(text.split())
        if len(line) > 220:
            line = line[:217].rsplit(" ", 1)[0] + "…"
        if self._pending:
            self.console.file.write("\r\033[2K")
            self._pending = False
        self.console.print(Text(f"    ✎ {line}", style="italic magenta"))

    def _record(self, r: HandoffRecord) -> None:
        self.records.append(r)
        if r.status == "SKIPPED":
            self.console.print(Text(f"\n○ {_step(r.agent_id)} {TITLES[r.agent_id]}  skipped", style="dim"))
            return
        if r.status == "AWAITING_FUND":
            self.console.print(Text(f"\n◔ {_step(r.agent_id)} {TITLES[r.agent_id]}  waiting for your fund", style="yellow"))
            return
        h = r.handoff
        border = {"COMPLETED": "green", "REJECTED": "red", "FAILED": "red"}[r.status]
        if h and h.signal.startswith(("RESIZE", "NEEDS MORE")):
            border = "yellow"
        title = Text(h.signal if h else r.status, style=f"bold {border}")
        if self.pro or r.plain is None:
            body = Table.grid(padding=(0, 2))
            body.add_column(style="bold", no_wrap=True)
            body.add_column()
            if h:
                body.add_row("SIGNAL", h.signal)
                body.add_row("OPINION", h.opinion)
                body.add_row("WHY", h.why_rationale)
        else:
            body = Text()
            body.append(r.plain.headline + "\n", style="bold")
            body.append(r.plain.what_it_means + "\n")
            body.append(r.plain.so_what, style="italic dim")
        produced = f"{r.produced.artifact_type} #{r.produced.sha}" if r.produced else "no artifact"
        if r.tokens:
            produced += f" · {r.tokens / 1000:.1f}k tokens · {r.latency_ms / 1000:.0f}s"
        self.console.print(Panel(body, title=title, title_align="left", subtitle=Text(f"handoff #{r.seq} · {produced}", style="dim"), subtitle_align="right", border_style=border, padding=(0, 1)))

    def summary(self, approval_route: str | None = None) -> str:
        return summarize(self.records, approval_route)

    def payload_table(self) -> None:
        t = Table(title="Handoff records", show_lines=False)
        for col in ("#", "role", "status", "consumed", "produced"):
            t.add_column(col)
        for r in self.records:
            consumed = ", ".join(f"{c.artifact_type}#{c.sha}" for c in r.consumed) or "–"
            produced = f"{r.produced.artifact_type}#{r.produced.sha}" if r.produced else "–"
            t.add_row(str(r.seq), r.agent_id, r.status, consumed, produced)
        self.console.print()
        self.console.print(t)
        for r in self.records:
            if r.output is not None:
                self.console.print(Text(f"\n#{r.seq} {r.agent_id} → {r.output_type}", style="bold"))
                self.console.print_json(data=r.output)


def summarize(records: list[HandoffRecord], approval_route: str | None = None, awaiting: Any = None) -> str:
    """One-line outcome of a run, shared by the CLI and the API. `awaiting` is a pending ApprovalTicket."""
    if awaiting is not None:
        return f"AWAITING YOUR APPROVAL · {awaiting.action} {awaiting.shares} {awaiting.ticker}"
    if approval_route == "rejected":
        return "REJECTED BY YOU · nothing traded"
    if approval_route == "expired":
        return "APPROVAL EXPIRED · nothing traded"
    by_agent: dict[str, HandoffRecord] = {}
    for r in records:
        by_agent[r.agent_id] = r
    risk = by_agent.get("risk_gate")
    if risk and risk.handoff and risk.handoff.signal.startswith("WHAT-IF"):
        return risk.handoff.signal + " · nothing traded"
    if set(by_agent) == {"research_analyst"}:
        r = by_agent["research_analyst"]
        return f"RESEARCH ONLY · {r.handoff.signal if r.handoff else r.status} · nothing traded"
    ledger = by_agent.get("portfolio_ledger")
    if ledger and ledger.status == "COMPLETED":
        out = ledger.output
        return f"FILLED & BOOKED · NAV ${out['nav_after']:,.2f} · cash ${out['cash_after']:,.2f}"
    risk = by_agent.get("risk_gate")
    if risk and risk.status == "REJECTED":
        return f"REJECTED at Risk Gate · {risk.handoff.signal}"
    pm = by_agent.get("portfolio_manager")
    if pm and pm.output_type == "Recommendation":
        o = pm.output
        return f"ADVICE: {o['action']} about {o['target_weight_pct']:.1f}% of your fund in {o['ticker']} (no fund set)"
    if pm and pm.output and pm.output.get("action") == "HOLD":
        return "HOLD · no trade placed"
    return "Run ended without a trade"
