"use client";
// The agent floor: five character cards (active one enlarged) and the active agent's stage.
import { useEffect, useRef, useState } from "react";
import type { AgentId, ApprovalTicket } from "@/lib/api";
import { LockIcon, PersonaIcon } from "./Icons";
import { LOCKS, ORDER, PERSONAS, type Scene, findItem, last, money, splitLabel, signalTone, stripMark } from "@/lib/scene";

const STATUS: Record<string, [string, string]> = {
  idle: ["Waiting", "idle"], work: ["Working…", "work"], done: ["Done", "done"], bad: ["Stopped", "bad"],
  resize: ["Sent it back", "wait"], skip: ["Not needed", "idle"], wait: ["Needs your fund", "wait"],
};

export function Floor({ scene, ticker, pro, onContinue, onDecide, busy }: {
  scene: Scene; ticker: string; pro: boolean; busy: boolean; onContinue: (cash: number) => void; onDecide: (d: "approve" | "reject") => void;
}) {
  const [picked, setPicked] = useState<AgentId | null>(null);
  const awaitingFund = !!scene.finished?.awaiting_fund;
  const yourCall = !!scene.approval && !!scene.finished?.awaiting_approval;
  const focus: AgentId = awaitingFund || yourCall ? "risk_gate" : picked ?? scene.current ?? "research_analyst";

  return (
    <>
      <div className="agents" role="list">
        {ORDER.map((id) => {
          const p = PERSONAS[id];
          const a = scene.agents[id];
          let [label, cls] = STATUS[a.status];
          if (id === "risk_gate" && awaitingFund) [label, cls] = ["Needs your fund", "wait"];
          if (id === "risk_gate" && scene.approval) [label, cls] = ["Your call", "wait"];
          const rec = last(a.recs);
          const chip = rec?.handoff && rec.status !== "SKIPPED" && rec.status !== "AWAITING_FUND" ? rec.handoff.signal : "";
          return (
            <button key={id} role="listitem" className={`agent t-${p.tone} ${focus === id ? "active" : ""} ${a.status === "idle" || a.status === "skip" ? "idle" : cls}`}
              onClick={() => setPicked(focus === id && picked ? null : id)} aria-label={`${p.name}, ${p.role}: ${label}`}>
              <span className="portrait"><PersonaIcon icon={p.icon} /></span>
              <span className="nm">{p.name}</span>
              <span className="rl">{p.role}</span>
              <span className="ty">{p.type}</span>
              <span className={`st ${cls}`}>{label}</span>
              {chip && <span className="handoff">→ {chip}</span>}
            </button>
          );
        })}
      </div>
      {picked && <button className="btn ghost small follow" onClick={() => setPicked(null)}>Follow live ↻</button>}
      <section className="panel stage" aria-live="polite">
        {focus === "research_analyst" && <Ava scene={scene} ticker={ticker} />}
        {focus === "portfolio_manager" && <Marcus scene={scene} />}
        {focus === "risk_gate" && <Vault scene={scene} onContinue={onContinue} onDecide={onDecide} busy={busy} />}
        {focus === "execution_trader" && <Kai scene={scene} />}
        {focus === "portfolio_ledger" && <Penny scene={scene} />}
      </section>
      <Narration scene={scene} pro={pro} />
    </>
  );
}

function Stamp({ signal }: { signal?: string }) {
  return signal ? <div><span className={`stamp ${signalTone(signal)}`}>{signal}</span></div> : null;
}

function Ava({ scene, ticker }: { scene: Scene; ticker: string }) {
  const a = scene.agents.research_analyst;
  const rec = last(a.recs);
  const running = scene.running?.agent === "research_analyst" && !["agent_think", "memory_write"].includes(scene.running.id) ? scene.running : null;
  const think = [...a.items].reverse().find((i) => i.id === "agent_think" && i.state !== "run");
  const thought = running ? `Reading: ${splitLabel(running.label).name}…` : a.thought ? a.thought.split(/\s+/).slice(-60).join(" ") : think ? stripMark(think.evidence) : a.starts ? `Opening the case file on ${ticker}…` : "Waiting for the case file…";
  const docs = a.items.filter((i) => !["agent_think", "memory_write", "submit_dossier", "sep"].includes(i.id));
  const score = findItem(a, "compute_scorecard");
  const base = score?.evidence ? parseFloat(/Base score ([\d.]+)/.exec(score.evidence)?.[1] ?? "0") : 0;
  const dossier = rec?.output_type === "ResearchDossier" ? rec.output : null;
  const conv = dossier ? dossier.conviction_score : base;
  return (
    <div className="split">
      <div className="col">
        <div className="label">Ava is investigating {ticker}</div>
        <div className="bubble">{thought}</div>
        <div>
          <div className="row-between"><span className="label">Conviction</span><span className="mono strong">{conv ? `${conv.toFixed(1)} / 10` : "–"}</span></div>
          <div className="meter"><div className="fill" style={{ width: `${conv * 10}%` }} /></div>
          <p className="note">{dossier ? `Formula ${dossier.scorecard.base_score.toFixed(1)}, Ava adjusted ${dossier.llm_adjustment >= 0 ? "+" : ""}${dossier.llm_adjustment.toFixed(1)}: ${dossier.adjustment_reason}` : base ? "Formula score from the baseline data; Ava may adjust it by up to ±1.5." : "Builds as evidence comes in."}</p>
        </div>
        <Stamp signal={rec?.handoff?.signal} />
      </div>
      <div className="col wide">
        <div className="row-between wrap">
          <div className="label">Evidence board · {docs.length} {docs.length === 1 ? "source" : "sources"}</div>
          {docs.some((d) => d.url) ? <span className="livebadge">LIVE DATA · SEC EDGAR + market feeds</span> : docs.length > 0 && <span className="badge">sample data</span>}
        </div>
        <div className="docs">
          {docs.map((d, i) => {
            const s = splitLabel(d.label);
            return (
              <div key={i} className={`doc ${d.state === "run" ? "run" : ""}`}>
                <span className="code">{s.code}</span>
                <div className="nm">{s.name}</div>
                <div className="ev">{d.state === "run" ? "pulling…" : d.evidence}</div>
                {d.url && <a className="src" href={d.url} target="_blank" rel="noopener noreferrer">{d.sourceLabel} ↗</a>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function Marcus({ scene }: { scene: Scene }) {
  const a = scene.agents.portfolio_manager;
  const rec = last(a.recs);
  const get = (id: string, fallback: string) => {
    const it = findItem(a, id);
    return it?.evidence ? stripMark(it.evidence) : fallback;
  };
  const weight: number | null = rec?.output?.target_weight_pct ?? null;
  const maxW = parseFloat(/Max ([\d.]+)%/.exec(get("get_fund_mandate", ""))?.[1] ?? "5");
  const C = 2 * Math.PI * 54;
  const dash = weight != null ? `${Math.min(C, (weight / maxW) * C).toFixed(1)} ${C.toFixed(1)}` : `0 ${C.toFixed(1)}`;
  const lines = [
    ["Your fund", get("get_portfolio_snapshot", "No fund set yet: Marcus will advise a share of your fund.")],
    ["Overlap with what you own", get("compute_correlation_beta", "Checking…")],
    ["How jumpy is the stock?", get("compute_realized_vol", "Measuring…")],
    ["Decision", get("pm_decide", "Thinking…")],
  ];
  return (
    <div className="split center">
      <div className="col">
        <div className="label">Marcus is sizing the trade{a.starts > 1 ? ` · attempt ${a.starts}` : ""}</div>
        {(a.starts ? lines : lines.slice(0, 1)).map(([k, v]) => (
          <div key={k} className="doc"><div className="nm first">{k}</div><div className="ev">{v}</div></div>
        ))}
      </div>
      <div className="col dial">
        <svg width="200" height="200" viewBox="0 0 140 140" role="img" aria-label={`Position size ${weight ?? 0}%`}>
          <circle cx="70" cy="70" r="54" fill="none" stroke="#16202B" strokeWidth="12" />
          <circle cx="70" cy="70" r="54" fill="none" stroke="#8B7CF6" strokeWidth="12" strokeLinecap="round" strokeDasharray={dash} transform="rotate(-90 70 70)" style={{ transition: "stroke-dasharray 1.2s ease" }} />
          <text x="70" y="70" textAnchor="middle" fill="#E6EDF3" fontSize="24" fontWeight="700" fontFamily="var(--font-mono)">{weight != null ? `${weight.toFixed(1)}%` : "–"}</text>
          <text x="70" y="90" textAnchor="middle" fill="#8B9BAA" fontSize="10">of fund · max {maxW}%</text>
        </svg>
        <div className="mono strong">{rec?.output?.shares ? `${rec.output.shares} shares · ${money(rec.output.dollar_amount)}` : rec?.output_type === "Recommendation" ? "Shares once your fund is set" : ""}</div>
        <Stamp signal={rec?.handoff?.signal} />
      </div>
    </div>
  );
}

function Vault({ scene, onContinue, onDecide, busy }: { scene: Scene; onContinue: (cash: number) => void; onDecide: (d: "approve" | "reject") => void; busy: boolean }) {
  const a = scene.agents.risk_gate;
  const rec = last(a.recs.filter((r) => r.status !== "AWAITING_FUND"));
  const advice = last(scene.agents.portfolio_manager.recs)?.output;
  const [cash, setCash] = useState("");
  const fundLine = findItem(a, "fund_check")?.evidence ?? "";
  const hitl = findItem(a, "hitl_approval");
  return (
    <div className="col">
      <div className="row-between wrap"><div className="label">The Vault · four locks between your money and the market</div><div className="note">{fundLine}</div></div>
      {scene.approval && scene.finished?.awaiting_approval && <YourCall ticket={scene.approval} onDecide={onDecide} busy={busy} />}
      {scene.finished?.awaiting_fund && (
        <form className="fundcard" onSubmit={(e) => { e.preventDefault(); const v = parseFloat(cash.replace(/[$,\s]/g, "")); if (v > 0) onContinue(v); }}>
          <div className="big">I can't check this until I know what you're working with.</div>
          <p>{advice ? `Marcus suggests putting about ${advice.target_weight_pct?.toFixed(1)}% of your portfolio into ${advice.ticker}. ` : ""}Tell me how much cash to work with and I'll turn it into shares and run the four checks. It's only a number: nothing is linked.</p>
          <label htmlFor="fcash" className="label amber">Cash to work with</label>
          <input id="fcash" className="field mono" inputMode="decimal" placeholder="e.g. 25,000" value={cash} onChange={(e) => setCash(e.target.value)} autoComplete="off" />
          <div className="actions">
            <button className="btn primary" type="submit" disabled={busy}>Continue with this cash</button>
          </div>
          <p className="note">Research is not repeated; Marcus re-sizes in shares. This amount becomes your saved portfolio. Trades stay simulated.</p>
        </form>
      )}
      <div className="locks">
        {LOCKS.map((L) => {
          const it = findItem(a, L.id);
          const s = !it ? "pending" : it.state === "run" ? "run" : it.state === "fail" ? "fail" : "open";
          return (
            <div key={L.id} className={`lock ${s}`}>
              <LockIcon state={s} />
              <div className="strong">{L.name}</div>
              <div className="note mono small">{it?.evidence ? stripMark(it.evidence) : s === "run" ? "checking…" : "locked"}</div>
            </div>
          );
        })}
      </div>
      {hitl && hitl.state !== "run" && <div className={`decision ${hitl.state === "fail" ? "bad" : "ok"}`}>{stripMark(hitl.evidence)}</div>}
      <Stamp signal={rec?.handoff?.signal} />
    </div>
  );
}

const HOLD_MS = 1200;

/** "Your call": the exact order, a live countdown, hold-to-approve and one-tap reject (D-026, D-043). */
function YourCall({ ticket, onDecide, busy }: { ticket: ApprovalTicket; onDecide: (d: "approve" | "reject") => void; busy: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  const [held, setHeld] = useState(0);
  const start = useRef<number | null>(null);
  const raf = useRef(0);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  const left = Math.max(0, new Date(ticket.expires_at).getTime() - now);
  const expired = left === 0;
  const mmss = `${Math.floor(left / 60000)}:${String(Math.floor((left % 60000) / 1000)).padStart(2, "0")}`;

  const step = () => {
    if (start.current === null) return;
    const p = Math.min(1, (performance.now() - start.current) / HOLD_MS);
    setHeld(p);
    if (p >= 1) {
      start.current = null;
      onDecide("approve");
    } else raf.current = requestAnimationFrame(step);
  };
  const press = () => {
    if (busy || start.current !== null) return;
    start.current = performance.now();
    raf.current = requestAnimationFrame(step);
  };
  const release = () => {
    if (start.current === null) return;
    start.current = null;
    cancelAnimationFrame(raf.current);
    setHeld(0);
  };

  return (
    <div className="yourcall" role="group" aria-label="Approve this simulated trade?">
      <div className="row-between wrap">
        <div className="label amber">Your call</div>
        <div className={`mono countdown ${expired ? "bad" : left < 120000 ? "warn" : ""}`} aria-live="off">{expired ? "Expired" : `Expires in ${mmss}`}</div>
      </div>
      <div className="big">Approve this simulated trade?</div>
      <div className="ticketgrid mono">
        <div><span className="label">Order</span>{ticket.action} {ticket.shares} {ticket.ticker}</div>
        <div><span className="label">Limit price</span>{money(ticket.limit_price)}</div>
        <div><span className="label">About</span>{money(ticket.dollar_amount, 0)} · {ticket.target_weight_pct.toFixed(1)}%</div>
        <div><span className="label">Stop-loss</span>{money(ticket.stop_loss_price)}</div>
        <div><span className="label">Safety checks</span>{ticket.rules_passed}/{ticket.rules_total} passed</div>
        <div><span className="label">Worst-day loss</span>{ticket.var_after_pct.toFixed(2)}% <span className="muted">of {ticket.var_limit_pct}%</span></div>
      </div>
      <p>{ticket.summary}</p>
      <p className="note">{expired
        ? "This ticket is older than 15 minutes. Approving sends the order back to The Vault for a fresh check first."
        : `If the price moves more than ${ticket.max_drift_pct}% before you approve, The Vault checks it again first.`} Simulated: nothing real is bought.</p>
      <div className="actions">
        <button className="btn primary holdbtn" disabled={busy} style={{ ["--held" as string]: held }}
          onPointerDown={press} onPointerUp={release} onPointerLeave={release} onPointerCancel={release} onContextMenu={(e) => e.preventDefault()}
          onKeyDown={(e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); press(); } }}
          onKeyUp={(e) => { if (e.key === " " || e.key === "Enter") release(); }}>
          <span>{busy ? "Working…" : held > 0 ? "Keep holding…" : "Hold to approve"}</span>
        </button>
        <button className="btn ghost" disabled={busy} onClick={() => onDecide("reject")}>Reject</button>
      </div>
    </div>
  );
}

function Kai({ scene }: { scene: Scene }) {
  const a = scene.agents.execution_trader;
  const tape = a.items.filter((i) => i.id === "poll_order_status" && i.state === "ok");
  const slip = findItem(a, "compute_slippage_bps")?.evidence;
  return (
    <div className="split">
      <div className="col">
        <div className="label">Kai is simulating the order at live prices, slice by slice. Nothing real is bought</div>
        <div className="doc"><div className="nm first">Order check</div><div className="ev">{findItem(a, "approval_match")?.evidence || "Waiting…"}</div></div>
        <div className="doc"><div className="nm first">Market right now</div><div className="ev">{findItem(a, "get_nbbo_quote")?.evidence || "–"}</div></div>
        {slip && <div><span className="stamp ok sm">{/= ([+-][\d.]+ bps)/.exec(slip)?.[1]} vs market</span></div>}
      </div>
      <div className="panel col wide tapebox">
        <div className="label pad">Simulated fill tape</div>
        {tape.map((t, i) => <div key={i} className="tape"><span className="muted">Slice {i + 1}</span><span>{t.evidence}</span></div>)}
      </div>
    </div>
  );
}

function Penny({ scene }: { scene: Scene }) {
  const a = scene.agents.portfolio_ledger;
  const rec = last(a.recs);
  const rows: [string, string][] = [["Simulated fills", "get_broker_positions"], ["Match", "reconcile_positions"], ["Tax lot", "book_tax_lot"], ["Cash", "settle_cash"], ["Fund value", "mark_to_market_nav"]];
  return (
    <div className="split">
      <div className="col wide">
        <div className="label">Penny is updating your portfolio (simulated)</div>
        <div className="receipt">
          <div className="rhead">NEXUS · SIMULATED TRADE RECEIPT</div>
          {rows.map(([k, id]) => <div key={k} className="ln"><span>{k}</span><span>{findItem(a, id)?.evidence ?? "…"}</span></div>)}
        </div>
      </div>
      <div className="col">
        <div className="label">Portfolio value</div>
        <div className="mono huge">{rec?.output ? money(rec.output.nav_after) : "–"}</div>
        {rec?.output && <div className="note">was {money(rec.output.nav_before)}</div>}
        {rec?.handoff && <div><span className="stamp ok">Booked ✓</span></div>}
      </div>
    </div>
  );
}

function Narration({ scene, pro }: { scene: Scene; pro: boolean }) {
  const who = scene.running ? scene.running.agent : scene.current;
  const text = scene.finished?.awaiting_fund ? "needs your cash to go further." : scene.running ? `${splitLabel(scene.running.label).name}…` : scene.finished ? "mission complete." : "handing off…";
  const r = scene.latest;
  return (
    <>
      <div className="narr">{who && <span className="who">{PERSONAS[who].name}:</span>}<span>{text}</span></div>
      {r && (
        <div className="panel latest">
          <div className="label">Latest handoff · {PERSONAS[r.agent_id].name}</div>
          <div className="strong">{pro || !r.plain ? r.handoff?.signal : r.plain.headline}</div>
          <p>{pro || !r.plain ? r.handoff?.why_rationale : r.plain.what_it_means}</p>
        </div>
      )}
      {scene.error && <div className="warn">Something went wrong: {scene.error}</div>}
    </>
  );
}
