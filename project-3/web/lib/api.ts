// Nexus API client: JSON calls plus Server-Sent Events read from a streamed POST response.
import { accessToken } from "./auth";

export type EngineEvent =
  | { type: "run_started"; command: string; journey: string; ticker: string; parent_id: string | null; fund: { nav: number; cash: number } | null }
  | { type: "agent_started"; run_id: string; agent_id: AgentId; note: string }
  | { type: "micro_action"; event: MicroAction }
  | { type: "agent_thought"; run_id: string; agent_id: AgentId; text: string; partial: boolean }
  | { type: "handoff_record"; record: HandoffRecord }
  | { type: "awaiting_approval"; run_id: string; ticket: ApprovalTicket }
  | { type: "run_finished"; run_id: string; outcome: string; awaiting_fund: boolean; awaiting_approval?: boolean; ticket?: ApprovalTicket | null }
  | { type: "error"; message: string };

export type AgentId = "research_analyst" | "portfolio_manager" | "risk_gate" | "execution_trader" | "portfolio_ledger";

export interface MicroAction {
  run_id: string;
  agent_id: AgentId;
  action_id: string;
  action_label: string;
  status: "IN_PROGRESS" | "COMPLETED" | "FAILED";
  evidence_snippet: string;
  source_label?: string | null;
  source_url?: string | null;
}

/** The exact order the run paused on (D-043). Approving after expires_at or a price move sends it back to The Vault. */
export interface ApprovalTicket {
  ticket_id: string;
  ticker: string;
  action: "BUY" | "SELL";
  shares: number;
  limit_price: number;
  dollar_amount: number;
  stop_loss_price: number;
  target_weight_pct: number;
  rules_passed: number;
  rules_total: number;
  var_after_pct: number;
  var_limit_pct: number;
  price_at_issue: number;
  issued_at: string;
  expires_at: string;
  max_drift_pct: number;
  summary: string;
}

export interface HandoffRecord {
  run_id: string;
  seq: number;
  agent_id: AgentId;
  status: "COMPLETED" | "FAILED" | "REJECTED" | "SKIPPED" | "AWAITING_FUND";
  output_type: string | null;
  output: Record<string, any> | null; // eslint-disable-line @typescript-eslint/no-explicit-any
  produced: { sha: string } | null;
  handoff: { signal: string; opinion: string; why_rationale: string } | null;
  plain: { headline: string; what_it_means: string; so_what: string } | null;
  tokens: number | null;
}

export interface Fund {
  cash: number;
  holdings: { ticker: string; shares: number; cost_basis: number }[];
  preset: "careful" | "balanced" | "bold";
}

export interface FundView {
  fund: Fund | null;
  snapshot?: { nav: number; cash: number; invested_pct: number };
  mandate?: Record<string, number>;
}

export interface RunSummary {
  id: string;
  command: string;
  journey: string;
  ticker: string;
  outcome: string;
  awaiting_fund: boolean;
  awaiting_approval?: boolean;
  created_at: string;
  parent_id: string | null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function headers(): Promise<HeadersInit> {
  const token = await accessToken();
  return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

async function check(res: Response): Promise<Response> {
  if (res.ok) return res;
  let detail = res.statusText;
  try {
    detail = (await res.json()).detail ?? detail;
  } catch {}
  throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
}

export async function getJson<T>(path: string): Promise<T> {
  return (await check(await fetch(path, { headers: await headers() }))).json();
}

export async function sendJson<T>(path: string, method: "PUT" | "DELETE", body?: unknown): Promise<T> {
  return (await check(await fetch(path, { method, headers: await headers(), body: body ? JSON.stringify(body) : undefined }))).json();
}

/** POST and read the response body as an SSE stream, calling onEvent for each event as it arrives. */
export async function streamRun(path: string, body: unknown, onEvent: (e: EngineEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await check(await fetch(path, { method: "POST", headers: await headers(), body: JSON.stringify(body), signal }));
  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const dataLine = block.split("\n").find((l) => l.startsWith("data: "));
      const eventLine = block.split("\n").find((l) => l.startsWith("event: "));
      if (!dataLine || !eventLine) continue;
      const payload = JSON.parse(dataLine.slice(6));
      onEvent({ ...payload, type: eventLine.slice(7) } as EngineEvent);
    }
  }
}
