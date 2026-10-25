// Turns the engine's event stream into what each agent card and stage shows (ported from the approved prototype).
import type { AgentId, ApprovalTicket, EngineEvent, HandoffRecord } from "./api";

export const ORDER: AgentId[] = ["research_analyst", "portfolio_manager", "risk_gate", "execution_trader", "portfolio_ledger"];

export const PERSONAS: Record<AgentId, { name: string; role: string; type: string; tone: "ai" | "code"; icon: string }> = {
  research_analyst: { name: "Ava", role: "Research Analyst", type: "AI", tone: "ai", icon: "search" },
  portfolio_manager: { name: "Marcus", role: "Portfolio Manager", type: "AI + formula", tone: "ai", icon: "dial" },
  risk_gate: { name: "The Vault", role: "Risk Gate", type: "Rules engine · no AI", tone: "code", icon: "lock" },
  execution_trader: { name: "Kai", role: "Trade Simulator", type: "Code · simulated", tone: "code", icon: "bolt" },
  portfolio_ledger: { name: "Penny", role: "Portfolio Ledger", type: "Code · no AI", tone: "code", icon: "book" },
};

export const LOCKS = [
  { id: "check_concentration", name: "Not too much in one stock" },
  { id: "check_cash_and_margin", name: "Enough cash to pay" },
  { id: "check_wash_sale", name: "No recent loss sale (tax rule)" },
  { id: "compute_marginal_var", name: "Worst-day loss stays small" },
];

export type ItemState = "run" | "ok" | "fail";
export interface Item { id: string; label: string; evidence: string; state: ItemState; sourceLabel?: string | null; url?: string | null }
export type AgentStatus = "idle" | "work" | "done" | "bad" | "resize" | "skip" | "wait";
export interface AgentView { items: Item[]; recs: HandoffRecord[]; starts: number; status: AgentStatus; thought: string }

export interface Scene {
  agents: Record<AgentId, AgentView>;
  current: AgentId | null;
  running: { agent: AgentId; label: string; id: string } | null;
  finished: { outcome: string; awaiting_fund: boolean; awaiting_approval: boolean; run_id: string } | null;
  approval: ApprovalTicket | null; // the ticket waiting for the user's call (D-043)
  error: string | null;
  latest: HandoffRecord | null;
}

function recStatus(r: HandoffRecord): AgentStatus {
  if (r.status === "SKIPPED") return "skip";
  if (r.status === "AWAITING_FUND") return "wait";
  if (r.status === "FAILED") return "bad";
  if (r.status === "REJECTED") return r.handoff?.signal.startsWith("RESIZE") ? "resize" : "bad";
  if (r.output_type === "TradeIntent" && r.output?.action === "HOLD") return "bad";
  return "done";
}

export function derive(events: EngineEvent[]): Scene {
  const agents = Object.fromEntries(ORDER.map((id) => [id, { items: [], recs: [], starts: 0, status: "idle", thought: "" } as AgentView])) as Record<AgentId, AgentView>;
  const open = new Map<string, Item>();
  const scene: Scene = { agents, current: null, running: null, finished: null, approval: null, error: null, latest: null };
  for (const e of events) {
    if (e.type === "run_started") {
      scene.finished = null; // a continued or resumed run replaces the previous ending
      scene.approval = null;
    } else if (e.type === "agent_started") {
      const a = agents[e.agent_id];
      a.starts += 1;
      a.status = "work";
      scene.current = e.agent_id;
      if (a.starts > 1 || e.note) a.items.push({ id: "sep", label: e.note || `Attempt ${a.starts}`, evidence: "", state: "ok" });
    } else if (e.type === "micro_action") {
      const m = e.event;
      const a = agents[m.agent_id];
      const key = `${m.run_id}|${m.agent_id}|${m.action_id}`;
      if (m.status === "IN_PROGRESS") {
        const item: Item = { id: m.action_id, label: m.action_label, evidence: "", state: "run" };
        open.set(key, item);
        a.items.push(item);
        scene.running = { agent: m.agent_id, label: m.action_label, id: m.action_id };
      } else {
        const item = open.get(key) ?? { id: m.action_id, label: m.action_label, evidence: "", state: "run" as ItemState };
        if (!open.has(key)) a.items.push(item);
        item.state = m.status === "FAILED" || m.evidence_snippet.startsWith("FAIL ·") ? "fail" : "ok";
        item.evidence = m.evidence_snippet;
        item.sourceLabel = m.source_label;
        item.url = m.source_url;
        if (m.action_id === "hitl_approval") a.status = item.state === "fail" ? "bad" : "done"; // the user decided
        open.delete(key);
        scene.running = null;
      }
    } else if (e.type === "agent_thought") {
      agents[e.agent_id].thought = e.text;
    } else if (e.type === "handoff_record") {
      const a = agents[e.record.agent_id];
      a.recs.push(e.record);
      a.status = recStatus(e.record);
      if (e.record.status !== "SKIPPED" && e.record.status !== "AWAITING_FUND") scene.latest = e.record;
    } else if (e.type === "awaiting_approval") {
      scene.approval = e.ticket;
      scene.current = "risk_gate";
      agents.risk_gate.status = "wait";
    } else if (e.type === "run_finished") {
      scene.finished = { outcome: e.outcome, awaiting_fund: e.awaiting_fund, awaiting_approval: !!e.awaiting_approval, run_id: e.run_id };
      if (!e.awaiting_approval) scene.approval = null;
    } else if (e.type === "error") {
      scene.error = e.message;
    }
  }
  return scene;
}

export const last = <T,>(xs: T[]): T | undefined => xs[xs.length - 1];
export const findItem = (a: AgentView, id: string) => [...a.items].reverse().find((i) => i.id === id);
export const stripMark = (s: string) => s.replace(/^(PASS|FAIL) · /, "").replace(/^→ /, "");
export const splitLabel = (l: string) => {
  const i = l.indexOf(" · ");
  return i < 0 ? { code: "", name: l } : { code: l.slice(0, i), name: l.slice(i + 3) };
};
export const signalTone = (sig?: string) =>
  !sig ? "ok" : /^(REJECTED|RESEARCH FAILED|HOLD|WHAT-IF: FAILS|APPROVAL EXPIRED)/.test(sig) ? "bad" : /^(RESIZE|NEEDS|BUY ADVICE|SELL ADVICE|AWAITING)/.test(sig) ? "warn" : "ok";

/** Cinematic pacing: real events, spaced out so each one can be seen. Quick mode is ~4x faster. */
export function dwellMs(e: EngineEvent, quick: boolean): number {
  const base =
    e.type === "agent_started" ? 900 :
    e.type === "handoff_record" ? 1800 :
    e.type === "micro_action" ? (e.event.action_id === "agent_think" ? (e.event.status === "IN_PROGRESS" ? 300 : 1200) : e.event.status === "IN_PROGRESS" ? 350 : 260) :
    e.type === "agent_thought" ? (e.partial ? 0 : 400) : 0;
  return quick ? base / 4 : base;
}

export const money = (x: number, digits = 2) => "$" + x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
