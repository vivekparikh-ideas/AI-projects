"use client";
// The show (D-026): setup → search → agent floor → mission report, plus run history. Live events from the API,
// paced so each one can be seen (pacing only spaces out real events; nothing is invented).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, type EngineEvent, type Fund, type FundView, type RunSummary, getJson, sendJson, streamRun } from "@/lib/api";
import { DEV_AUTH, sendMagicLink, signInWithPassword, signOut, supabase } from "@/lib/auth";
import { PERSONAS, derive, dwellMs, money, signalTone } from "@/lib/scene";
import { Floor } from "./Floor";
import { Mark, PersonaIcon } from "./Icons";
import { InstallButton } from "./InstallButton";

type Screen = "loading" | "login" | "setup" | "search" | "floor" | "report" | "history";
const PRESETS = [
  { id: "careful", name: "Careful", desc: "max 3% per stock" },
  { id: "balanced", name: "Balanced", desc: "max 5% per stock" },
  { id: "bold", name: "Bold", desc: "max 8% per stock" },
] as const;
const JOURNEYS = ["Evaluate NVDA", "Research TSLA", "Can I add $5k of MSFT?", "Evaluate LLY"];
const SETUP_SEEN = "nexus.setupSeen";

export default function NexusApp() {
  const [screen, setScreen] = useState<Screen>("loading");
  const [fund, setFund] = useState<FundView>({ fund: null });
  const [pro, setPro] = useState(false);
  const [quick, setQuick] = useState(false);
  const [message, setMessage] = useState("");
  const [title, setTitle] = useState("");
  const [ticker, setTicker] = useState("");
  const [shown, setShown] = useState<EngineEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const queue = useRef<EngineEvent[]>([]);
  const quickRef = useRef(quick);
  quickRef.current = quick;

  // ── pacing loop: move queued events onto the floor one at a time ──
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const next = queue.current.shift();
      if (next) {
        setShown((s) => [...s, next]);
        timer = setTimeout(tick, dwellMs(next, quickRef.current));
      } else timer = setTimeout(tick, 120);
    };
    tick();
    return () => clearTimeout(timer);
  }, []);

  const scene = useMemo(() => derive(shown), [shown]);
  const done = !!scene.finished && !scene.finished.awaiting_fund && !scene.finished.awaiting_approval && queue.current.length === 0 && !busy;
  const [pending, setPending] = useState<RunSummary[]>([]);

  // ── auth + fund ──
  const loadFund = useCallback(async () => {
    try {
      const view = await getJson<FundView>("/api/fund");
      setFund(view);
      return view;
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        setMessage(e.message);
        setScreen("login");
      }
      return null;
    }
  }, []);

  const loadPending = useCallback(async () => {
    try {
      const { runs } = await getJson<{ runs: RunSummary[] }>("/api/runs");
      setPending(runs.filter((r) => r.awaiting_approval));
    } catch {}
  }, []);

  const enter = useCallback(async () => {
    const view = await loadFund();
    if (!view) return;
    loadPending();
    const seen = typeof window !== "undefined" && localStorage.getItem(SETUP_SEEN) === "1";
    setScreen(view.fund || seen ? "search" : "setup");
  }, [loadFund, loadPending]);

  useEffect(() => {
    if (DEV_AUTH) {
      enter();
      return;
    }
    const sb = supabase();
    if (!sb) {
      setScreen("login");
      setMessage("Sign-in is not configured (missing Supabase settings).");
      return;
    }
    sb.auth.getSession().then(({ data }) => (data.session ? enter() : setScreen("login")));
    const { data: sub } = sb.auth.onAuthStateChange((event, session) => {
      if (event === "SIGNED_IN" && session) enter();
      if (event === "SIGNED_OUT") setScreen("login");
    });
    return () => sub.subscription.unsubscribe();
  }, [enter]);

  useEffect(() => {
    if (done && screen === "floor") {
      const t = setTimeout(() => setScreen("report"), quick ? 600 : 1800);
      return () => clearTimeout(t);
    }
  }, [done, screen, quick]);

  // ── runs ──
  const run = useCallback(async (command: string) => {
    setMessage("");
    queue.current = [];
    setShown([]);
    setTitle(command);
    setTicker((/([A-Za-z.]{1,6})\??\s*$/.exec(command)?.[1] ?? "").toUpperCase());
    setScreen("floor");
    setBusy(true);
    try {
      await streamRun("/api/runs", { command }, (e) => queue.current.push(e));
    } catch (e) {
      setScreen("search");
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      loadFund();
      loadPending();
    }
  }, [loadFund, loadPending]);

  // Resume a run paused at "Your call"; its events continue on the same floor.
  const decide = useCallback(async (decision: "approve" | "reject") => {
    if (!scene.finished?.awaiting_approval) return;
    setBusy(true);
    try {
      await streamRun(`/api/runs/${scene.finished.run_id}/approve`, { decision }, (e) => queue.current.push(e));
    } catch (e) {
      queue.current.push({ type: "error", message: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
      loadFund();
      loadPending();
    }
  }, [scene.finished, loadFund, loadPending]);

  const continueWithCash = useCallback(async (cash: number) => {
    if (!scene.finished) return;
    setBusy(true);
    try {
      await streamRun(`/api/runs/${scene.finished.run_id}/continue`, { cash }, (e) => queue.current.push(e));
    } catch (e) {
      queue.current.push({ type: "error", message: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
      loadFund();
    }
  }, [scene.finished, loadFund]);

  const replay = useCallback(async (r: RunSummary) => {
    const saved = await getJson<{ events: EngineEvent[] }>(`/api/runs/${r.id}`);
    // Saved events stop before the stream's closing line; restore it from the saved summary so a paused run can be decided.
    const ending: EngineEvent = { type: "run_finished", run_id: r.id, outcome: r.outcome, awaiting_fund: r.awaiting_fund, awaiting_approval: !!r.awaiting_approval };
    queue.current = [...saved.events, ending];
    setShown([]);
    setTitle(r.command);
    setTicker(r.ticker);
    setScreen("floor");
  }, []);

  const skip = () => {
    const rest = queue.current; // take the events now: the state updater runs later, after the queue is cleared
    queue.current = [];
    setShown((s) => [...s, ...rest]);
  };

  // ── screens ──
  if (screen === "loading") return <div className="center-screen"><Mark size={44} /></div>;
  if (screen === "login") return <Login message={message} />;
  if (screen === "setup") return <Setup fund={fund.fund} onDone={async (f) => { if (f) setFund(await sendJson<FundView>("/api/fund", "PUT", f)); localStorage.setItem(SETUP_SEEN, "1"); setScreen("search"); }} />;
  if (screen === "history") return <History onPick={replay} onBack={() => setScreen("search")} />;

  const header = (
    <header className="topbar">
      <button className="btn ghost small" onClick={() => setScreen("search")} aria-label="Back to search"><Mark size={22} /> NEXUS</button>
      {screen !== "search" && <span className="mono strong ellipsis">{title}</span>}
      <span className="practice" title="Real research on live data. Trades are simulated: no real money, no linked accounts">SIMULATED TRADES</span>
      <Metrics fund={fund} pro={pro} onAdd={() => setScreen("setup")} />
      <span className="grow" />
      {screen === "floor" && <button className={`chip ${quick ? "on" : ""}`} onClick={() => setQuick(!quick)}>Quick</button>}
      <button className={`chip ${pro ? "on" : ""}`} onClick={() => setPro(!pro)}>Pro</button>
      {screen === "floor" && <button className="btn small" onClick={skip}>Skip ⏭</button>}
    </header>
  );

  if (screen === "search") {
    return (
      <div className="app">
        {header}
        {pending.length > 0 && (
          <div className="wrap"><div className="pendingbar">
            <span><b>Your call:</b> {pending.length === 1 ? `a simulated trade is waiting for your approval (${pending[0].outcome.replace("AWAITING YOUR APPROVAL · ", "")})` : `${pending.length} simulated trades are waiting for your approval`}</span>
            <span className="grow" />
            <button className="btn small primary" onClick={() => replay(pending[0])}>Review</button>
          </div></div>
        )}
        <Search message={message} onRun={run} onHistory={() => setScreen("history")} onSignOut={DEV_AUTH ? undefined : async () => { await signOut(); }} />
      </div>
    );
  }

  if (screen === "report") {
    return (
      <div className="app">
        {header}
        <Report scene={scene} title={title} pro={pro} onAgain={() => setScreen("search")} onWatch={() => { queue.current = [...shown]; setShown([]); setScreen("floor"); }} onHistory={() => setScreen("history")} />
      </div>
    );
  }

  return (
    <div className="app">
      {header}
      <main className="wrap floor">
        <Floor scene={scene} ticker={ticker} pro={pro} onContinue={continueWithCash} onDecide={decide} busy={busy} />
        {scene.finished?.awaiting_fund && !busy && (
          <div className="actions center"><button className="btn ghost" onClick={() => setScreen("report")}>Just tell me what you think →</button></div>
        )}
        {scene.finished?.awaiting_approval && !busy && (
          <div className="actions center"><button className="btn ghost" onClick={() => { loadPending(); setScreen("search"); }}>Decide later</button></div>
        )}
        {done && <div className="actions center"><button className="btn primary" onClick={() => setScreen("report")}>Mission report →</button></div>}
      </main>
    </div>
  );
}

function Metrics({ fund, pro, onAdd }: { fund: FundView; pro: boolean; onAdd: () => void }) {
  const s = fund.snapshot;
  if (!fund.fund || !s) return <button className="pill" onClick={onAdd}>No portfolio set · Add one</button>;
  const items = pro
    ? [["NAV", money(s.nav, 0)], ["Settled cash", money(s.cash, 0)], ["Gross exposure", `${s.invested_pct.toFixed(1)}%`]]
    : [["Portfolio value", money(s.nav, 0)], ["Cash", money(s.cash, 0)], ["Invested", `${s.invested_pct.toFixed(1)}%`]];
  return (
    <div className="metrics">
      {items.map(([k, v]) => <div key={k} className="metric"><div className="label">{k}</div><div className="v mono">{v}</div></div>)}
    </div>
  );
}

function Login({ message }: { message: string }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"password" | "link">("password");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(message);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    const err = mode === "password" ? await signInWithPassword(email.trim(), password) : await sendMagicLink(email.trim());
    setBusy(false);
    if (err) setError(/rate limit/i.test(err) ? "Too many sign-in emails for now. Use your password instead, or try the link again in an hour." : err);
    else if (mode === "link") setSent(true);
  };
  return (
    <div className="center-screen">
      <form className="panel narrow" onSubmit={submit}>
        <div className="brand"><Mark size={34} /><span>NEXUS</span></div>
        <h1>Your agents are waiting.</h1>
        {sent ? <p>Check your email for a sign-in link, then open it in Chrome on this device.</p> : (
          <>
            <label htmlFor="email" className="label">Email</label>
            <input id="email" type="email" className="field" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
            {mode === "password" && (
              <>
                <label htmlFor="password" className="label">Password</label>
                <input id="password" type="password" className="field" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
              </>
            )}
            <button className="btn primary full" type="submit" disabled={busy}>{mode === "password" ? "Sign in" : "Email me a sign-in link"}</button>
            <button type="button" className="btn ghost small" onClick={() => { setMode(mode === "password" ? "link" : "password"); setError(""); }}>
              {mode === "password" ? "Use an email link instead" : "Use my password instead"}
            </button>
          </>
        )}
        {error && <p className="warn">{error}</p>}
        <p className="note">Private: only the owner's email can use this Nexus.</p>
      </form>
    </div>
  );
}

function Setup({ fund, onDone }: { fund: Fund | null; onDone: (f: Fund | null) => void }) {
  const [cash, setCash] = useState(fund ? String(fund.cash) : "");
  const [preset, setPreset] = useState<Fund["preset"]>(fund?.preset ?? "balanced");
  const [rows, setRows] = useState(fund?.holdings.length ? fund.holdings.map((h) => ({ t: h.ticker, s: String(h.shares), c: String(h.cost_basis) })) : [{ t: "", s: "", c: "" }]);
  const [error, setError] = useState("");
  const save = () => {
    const c = parseFloat(cash.replace(/[$,\s]/g, ""));
    if (!(c >= 0) || cash.trim() === "") return setError("Enter your available cash, or choose Skip for now.");
    const holdings = rows.filter((r) => r.t.trim()).map((r) => ({ ticker: r.t.trim().toUpperCase(), shares: parseFloat(r.s), cost_basis: parseFloat(r.c) }));
    if (holdings.some((h) => !(h.shares > 0) || !(h.cost_basis > 0))) return setError("Each stock needs shares and the average price you paid.");
    onDone({ cash: c, holdings, preset });
  };
  return (
    <div className="app">
      <div className="wrap narrowcol">
        <div className="brand"><Mark size={30} /><span>NEXUS</span></div>
        <h1 className="hero">See what your research desk would do with your portfolio.</h1>
        <p className="lede">Five AI and rule-based agents research a stock, decide how much fits your portfolio, check the risks and simulate the trade, so you can see what they'd do before you do anything yourself.</p>
        <ul className="promises">
          <li><b>No bank or brokerage linking.</b> Ever.</li>
          <li><b>No real money moves.</b> Every trade here is a simulation.</li>
          <li><b>Your numbers stay private.</b> Only you can sign in.</li>
        </ul>
        <div className="panel form">
          <label htmlFor="cash" className="label">How much cash do you want to work with?</label>
          <input id="cash" className="field mono big" inputMode="decimal" placeholder="e.g. 25,000" value={cash} onChange={(e) => setCash(e.target.value)} />
          <div className="label">Stocks you own (optional)</div>
          <p className="note">Typing them in lets the agents check how a new stock overlaps with what you hold. We never connect to your broker. Use your real numbers for realistic advice, or any amount you like.</p>
          {rows.map((r, i) => (
            <div key={i} className="grid3">
              <input className="field mono" aria-label={`Ticker ${i + 1}`} placeholder="Ticker" value={r.t} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, t: e.target.value.toUpperCase() } : x)))} />
              <input className="field mono" aria-label={`Shares ${i + 1}`} placeholder="Shares" inputMode="decimal" value={r.s} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, s: e.target.value } : x)))} />
              <input className="field mono" aria-label={`Average price ${i + 1}`} placeholder="Avg price $" inputMode="decimal" value={r.c} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, c: e.target.value } : x)))} />
            </div>
          ))}
          <button className="btn ghost small" onClick={() => setRows([...rows, { t: "", s: "", c: "" }])}>+ Add a stock</button>
          <div className="label">How bold should they be?</div>
          <div className="chips">
            {PRESETS.map((p) => <button key={p.id} className={`chip ${preset === p.id ? "on" : ""}`} onClick={() => setPreset(p.id)}><b>{p.name}</b> <span className="muted">{p.desc}</span></button>)}
          </div>
          {error && <div className="warn">{error}</div>}
          <div className="actions">
            <button className="btn primary" onClick={save}>Save my portfolio</button>
            <span className="grow" />
            <button className="btn ghost" onClick={() => onDone(null)}>Skip for now →</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Search({ message, onRun, onHistory, onSignOut }: { message: string; onRun: (c: string) => void; onHistory: () => void; onSignOut?: () => void }) {
  const [q, setQ] = useState("");
  return (
    <main className="wrap searchscreen">
      <div className="brand big"><Mark size={46} /><span>NEXUS</span></div>
      <h1 className="valueline">Your AI research desk reads the filings so you don't have to.</h1>
      <p className="valuesub">Ava reads SEC 10-Ks, 10-Qs, insider trades and much more... Marcus turns them into buy, hold or sell, and how much fits your portfolio.</p>
      <form className="searchform" onSubmit={(e) => { e.preventDefault(); if (q.trim()) onRun(q.trim()); }}>
        <label htmlFor="q" className="sr-only">Ask your agents</label>
        <input id="q" className="field search" placeholder="Evaluate a stock… e.g. NVDA" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" autoCapitalize="characters" enterKeyHint="go" />
      </form>
      <div className="chips center">
        {JOURNEYS.map((j) => <button key={j} className="chip" onClick={() => onRun(j)}>{j}</button>)}
        <button className="chip" disabled>Check my stocks <span className="muted">M3</span></button>
      </div>
      {message && <div className="warn">{message}</div>}
      <HowItWorks />
      <div className="actions center">
        <InstallButton />
        <button className="btn ghost small" onClick={onHistory}>Past runs</button>
        {onSignOut && <button className="btn ghost small" onClick={onSignOut}>Sign out</button>}
      </div>
      <p className="note center">Trades are simulated: no accounts linked, no real money moves. For education, not investment advice.</p>
    </main>
  );
}

function plainOutcome(outcome: string): string {
  if (outcome.startsWith("FILLED")) return "Simulated trade complete.";
  if (outcome.startsWith("ADVICE")) return outcome.replace("ADVICE: ", "Advice: ").replace(" (no fund set)", "");
  if (outcome.startsWith("REJECTED BY YOU")) return "You rejected the trade. Nothing was simulated.";
  if (outcome.startsWith("APPROVAL EXPIRED")) return "Your approval expired too many times. Nothing was simulated.";
  if (outcome.startsWith("AWAITING YOUR APPROVAL")) return "Waiting for your approval.";
  if (outcome.startsWith("REJECTED")) return "The Vault stopped this trade.";
  if (outcome.startsWith("HOLD")) return "Marcus says hold. No trade.";
  if (outcome.startsWith("WHAT-IF: PASSES")) return "Yes, that trade would pass the safety checks.";
  if (outcome.startsWith("WHAT-IF: FAILS")) return "No, that trade would be blocked.";
  if (outcome.startsWith("RESEARCH ONLY")) return "Research complete.";
  return outcome;
}

function OrderHandoff({ order }: { order: Record<string, any> }) { // eslint-disable-line @typescript-eslint/no-explicit-any
  const [copied, setCopied] = useState(false);
  const text = order.shares
    ? `${order.action} ${order.shares} ${order.ticker} · limit $${order.limit_price.toFixed(2)} · stop-loss $${order.stop_loss_price.toFixed(2)}`
    : `${order.action} ${order.ticker} · about ${order.target_weight_pct.toFixed(1)}% of your portfolio · limit $${order.limit_price.toFixed(2)} · stop-loss $${order.stop_loss_price.toFixed(2)}`;
  return (
    <div className="panel handoffcard">
      <div className="label">If you want to act on it</div>
      <p>Place the order yourself in your own brokerage app. Nexus never trades for you.</p>
      <div className="ordertext mono">{text}</div>
      <button className="btn small" onClick={async () => { await navigator.clipboard.writeText(text); setCopied(true); }}>{copied ? "Copied ✓" : "Copy order details"}</button>
    </div>
  );
}

function Verdict({ scene }: { scene: ReturnType<typeof derive> }) {
  const research = [...scene.agents.research_analyst.recs].reverse().find((r) => r.output_type === "ResearchDossier");
  const pmRec = [...scene.agents.portfolio_manager.recs].reverse().find((r) => r.output?.action);
  const d = research?.output;
  if (!d) return null;
  const pm = pmRec?.output;
  const action = pm?.action ?? "Research only";
  const sizing = pm && pm.action !== "HOLD" && pm.target_weight_pct ? ` · about ${pm.target_weight_pct.toFixed(1)}% of your portfolio` : "";
  return (
    <section className="panel verdict">
      <div className="label">The research desk's verdict</div>
      <div className="verdictline"><span className={`stamp ${action === "BUY" ? "ok" : action === "HOLD" ? "warn" : "ok"}`}>{action}</span><span className="mono strong">{d.ticker}{sizing}</span></div>
      <div className="mono">Conviction {d.conviction_score.toFixed(1)}/10 <span className="muted">(formula {d.scorecard.base_score.toFixed(1)}, Ava {d.llm_adjustment >= 0 ? "+" : ""}{d.llm_adjustment.toFixed(1)})</span></div>
      <div className="case"><b>Bull case.</b> {d.bull_case}</div>
      <div className="case"><b>Bear case.</b> {d.bear_case}</div>
      <div className="case"><b>Why Ava adjusted.</b> {d.adjustment_reason}</div>
      {d.notes?.length > 0 && <div className="case"><b>Answer to Marcus.</b> {d.notes[d.notes.length - 1]}</div>}
      {d.reading_summary && <div className="note">What Ava read: {d.reading_summary}. Every number above is traced to these sources.</div>}
      {d.sources?.some((x: { url?: string }) => x.url) && (
        <div className="sources">
          {d.sources.filter((x: { url?: string }) => x.url).map((x: { label: string; url: string; tool: string }, i: number) => (
            <a key={i} className="src" href={x.url} target="_blank" rel="noopener noreferrer">{x.label} ↗</a>
          ))}
        </div>
      )}
    </section>
  );
}

const DESK = [
  { id: "research_analyst", does: "Reads the latest 10-K and 10-Q, insider trades (Form 4), financials and a year of prices, then picks what to dig into." },
  { id: "portfolio_manager", does: "Decides buy, hold or sell, and how much fits your portfolio, with a limit price and a stop-loss." },
  { id: "risk_gate", does: "Checks the size, your cash, the wash-sale tax rule and the worst-day loss. Rules, not AI." },
] as const;

function HowItWorks() {
  return (
    <section className="howitworks" aria-label="How your desk works">
      <div className="label center">How your desk works</div>
      <div className="deskrow">
        {DESK.map((d, i) => {
          const p = PERSONAS[d.id];
          return (
            <div key={d.id} className={`deskcard t-${p.tone}`}>
              <div className="deskhead">
                <span className="portrait sm"><PersonaIcon icon={p.icon} /></span>
                <div><b>{p.name}</b><div className="note">{p.role} · {p.type}</div></div>
                {i < DESK.length - 1 && <span className="deskarrow" aria-hidden="true">→</span>}
              </div>
              <p>{d.does}</p>
            </div>
          );
        })}
      </div>
      <p className="note center">Then Kai simulates the trade at live prices and Penny updates your portfolio. You place any real order yourself.</p>
    </section>
  );
}

function Report({ scene, title, pro, onAgain, onWatch, onHistory }: { scene: ReturnType<typeof derive>; title: string; pro: boolean; onAgain: () => void; onWatch: () => void; onHistory: () => void }) {
  const outcome = scene.finished?.outcome ?? scene.error ?? "Run ended.";
  const tone = scene.finished?.awaiting_fund ? "warn" : signalTone(outcome.startsWith("FILLED") || outcome.startsWith("WHAT-IF: PASSES") ? "OK" : outcome.startsWith("REJECTED") || outcome.startsWith("HOLD") || outcome.startsWith("WHAT-IF: FAILS") || outcome.startsWith("APPROVAL EXPIRED") ? "REJECTED" : outcome.startsWith("ADVICE") ? "BUY ADVICE" : "OK");
  const story = Object.values(scene.agents).flatMap((a) => a.recs).filter((r) => r.status !== "SKIPPED" && r.status !== "AWAITING_FUND").sort((a, b) => a.seq - b.seq);
  const pm = [...scene.agents.portfolio_manager.recs].reverse().find((r) => r.output && r.output.action && r.output.action !== "HOLD");
  const order = pm?.output && !outcome.startsWith("REJECTED") && !outcome.startsWith("HOLD") ? pm.output : null;
  return (
    <main className="wrap narrowcol">
      <div className="label">Mission report · {title}</div>
      <Verdict scene={scene} />
      <div className="label">Simulated trade</div>
      <div className={`outcome ${tone}`}>{pro ? outcome : plainOutcome(outcome)}</div>
      {scene.finished?.awaiting_fund && <p className="lede">No portfolio was set, so nothing was simulated. Add your cash any time to see it in shares.</p>}
      {outcome.startsWith("FILLED") && <p className="lede">If you made this trade, here's how it would have looked in your portfolio. The trade was simulated; nothing real was bought.</p>}
      {order && <OrderHandoff order={order} />}
      <div className="panel story">
        {story.map((r, i) => {
          const p = PERSONAS[r.agent_id];
          return (
            <div key={i} className={`storyrow t-${p.tone}`}>
              <span className="portrait sm">{p.name.replace("The ", "")[0]}</span>
              <div>
                <div className="row-wrap"><b>{p.name}</b><span className="note">{p.role}</span><span className={`badge ${signalTone(r.handoff?.signal)}`}>{r.handoff?.signal ?? r.status}</span></div>
                <p>{pro || !r.plain ? r.handoff?.why_rationale : `${r.plain.headline} ${r.plain.what_it_means}`}</p>
              </div>
            </div>
          );
        })}
      </div>
      <p className="note">Trades are simulated. For education, not investment advice.</p>
      <div className="actions">
        <button className="btn primary" onClick={onAgain}>Ask another</button>
        <button className="btn" onClick={onWatch}>Watch again</button>
        <button className="btn ghost" onClick={onHistory}>Past runs</button>
      </div>
    </main>
  );
}

function History({ onPick, onBack }: { onPick: (r: RunSummary) => void; onBack: () => void }) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  useEffect(() => { getJson<{ runs: RunSummary[] }>("/api/runs").then((r) => setRuns(r.runs)).catch(() => setRuns([])); }, []);
  return (
    <div className="app">
      <main className="wrap narrowcol">
        <button className="btn ghost small" onClick={onBack}>← Back</button>
        <h1 className="hero">Past runs</h1>
        {runs === null ? <p className="note">Loading…</p> : runs.length === 0 ? <p className="note">No runs yet.</p> : (
          <div className="panel story">
            {runs.map((r) => (
              <button key={r.id} className="runrow" onClick={() => onPick(r)}>
                <span className="mono strong">{r.command}</span>
                <span className="note">{new Date(r.created_at).toLocaleString()}{r.parent_id ? " · continued" : ""}</span>
                <span className={`badge ${r.awaiting_fund || r.awaiting_approval ? "warn" : signalTone(r.outcome.startsWith("REJECTED") || r.outcome.startsWith("HOLD") ? "REJECTED" : "OK")}`}>{r.outcome}</span>
              </button>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
