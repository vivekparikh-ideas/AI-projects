# Nexus Investment Engine — Requirements

Living spec: describes **what** the system must do, edited in place. **Why** lives in [DECISIONS.md](DECISIONS.md); IDs like `D-006` point there.
Last updated: 2026-10-22.

---

## 1. Purpose

A private **practice** investment team run by AI and rule-based roles (D-038). The user asks about a stock; named agents research it, decide how much would fit the user's portfolio, check the risks, simulate the trade at live prices and update a practice portfolio. **No bank or brokerage account is ever linked and no real money moves**; the cash and holdings the user types are numbers for exploring allocation. To act on an idea, the user places the order themselves in their own brokerage app (the mission report gives copyable order details). Every step is visible live as a show, and every handoff is recorded.

### 1a. User journeys (D-023)

| # | Journey | Command | Roles involved | Ends with |
|---|---|---|---|---|
| 1 | Evaluate an idea | `Evaluate NVDA` | All five | Trade (after approval), HOLD, or rejection |
| 2 | Research only | `Research TSLA` | Research Analyst | Dossier + plain-English report; never trades |
| 3 | What-if | `Can I add $50k of AMD?` | Risk Gate on a hypothetical order | Pass/fail verdict per rule |
| 4 | Watchlist scan | `Scan watchlist` (on demand; morning schedule from M4) | Journey 1 per ticker | Ranked ideas; each BUY is its own approval card |
| 5 | Position monitor | `Check my stocks` (scheduled from M3) | Research → PM (SELL) → Risk → approval → Execution → Ledger | SELL proposals for holdings that hit a stop-loss or moved sharply |

Default mode: every BUY or SELL that passes the Risk Gate waits for the user's approval (D-022).

CLI (M2): `python run_cli.py --ask "<command>" [--live] [--fund auto|none|sample|file]`; `python run_cli.py setup` writes `fund.yaml`, which runs then use automatically. `nexus/router.py` parses commands; monitor and scan answer with the milestone they arrive in.

### 1b. Fund setup (D-021)
- First run shows a setup screen: available cash, optional holdings (ticker, shares, cost basis, date acquired), and a risk preset.
- Presets map to the mandate: **Careful** (3% per stock, 1.5% worst-day loss), **Balanced** (5%, 2.5%), **Bold** (8%, 4%). Values are editable.
- Setup is skippable. No hypothetical money is ever invented.
- Stored in `fund.yaml` (M1.5–M2), then the SQLite ledger (M3). Replaces the hard-coded `MANDATE` and sample portfolio.

### 1c. Runs without a fund (D-021)
- Research and the PM run normally; the PM recommends a **percentage of the fund** (`Recommendation`), with no shares or dollars.
- Before the Risk Gate, `fund_check` pauses: the user enters cash (and optional holdings) to continue at sizing without re-running research, or chooses "Just tell me what you think" for an advice-only report.
- CLI before M3: prompts for cash at that point. M3+: a real `interrupt()` pause and resume.
- The header shows "No fund set · Add cash" instead of zeros.

## 2. Architecture

**Pattern:** sequential pipeline with an embedded ReAct research agent, bounded LLM-decided feedback loops, and a human approval gate (D-001, D-017, D-018).

```
command → journey_router ─┬ evaluate / research / monitor → research_analyst ⇄ portfolio_manager
                          │      research-only ends after the dossier ─────────────────────────▶ report
                          └ what-if → risk_gate (hypothetical order) ──────────────────────────▶ report
portfolio_manager → fund_check ─ no fund → fund card → continue │ advice only ─────────────────▶ report
                  → risk_gate ─pass→ hitl_approval (queue) ─approve→ execution_trader → portfolio_ledger → report
                      ↑ resize once (fixable fail)    │ expired / market closed → risk_gate at open
                      wash-sale / 2nd fail → END      reject → END
scan = one evaluate run per watchlist ticker, each with its own approval
```

| # | Role (`agent_id`) | Type | Decides |
|---|---|---|---|
| 1 | `research_analyst` | ReAct agent (LLM) | Which follow-up tools to call (D-017) |
| 2 | `portfolio_manager` | LLM + deterministic sizing | BUY / SELL / HOLD / NEED_MORE_RESEARCH (D-018) |
| 3 | `risk_gate` | Deterministic Python | PASS / REJECT / send back to PM (D-018) |
| 4 | `execution_trader` | Deterministic Python | Nothing; executes the approved order only |
| 5 | `portfolio_ledger` | Deterministic Python | Nothing; reconciles and books |

**R-ARCH-1** Roles 3–5 never call an LLM (D-002).
**R-ARCH-2** Every loop has a hard cap: research agent ≤ 8 tool calls; PM→Research ≤ 1; Risk→PM ≤ 1 (D-018).
**R-ARCH-3** Founder approval precedes any order: `request_approval` issues the ticket, then `hitl_approval` pauses with a real `interrupt()` saved by the Postgres checkpointer (D-009, D-043).
**R-ARCH-4** `journey_router` is a deterministic command parser, never an LLM (D-023). `fund_check` is deterministic.
**R-ARCH-5** Personas (Ava, Marcus, The Vault, Kai, Penny) live only in the UI; engine `agent_id`s are unchanged (D-026).
**R-ARCH-6** Several runs can wait for approval at once (approvals queue); each has its own pause, expiry and market-hours hold (D-025).

## 3. Roles

### 3.1 Research Analyst
- Input: `ticker` (+ optional `pm_question` on a second round).
- Baseline, always run by code: R2, R7, R8, R9, then R11 (scorecard from those results).
- Agent loop: picks follow-up tools from its registry, each call carries a `reason`; ends by calling `submit_dossier`.
- Output: `ResearchDossier`; conviction = scorecard `base_score` + LLM adjustment within ±1.5 with a required reason (D-016).
- Scorecard (R11): 30% growth (revenue growth ÷ 10) + 25% trend (4 if spot > 200-DMA, 3 if > 50-DMA, 3 if RSI 40–70) + 20% valuation (10 − 0.35 × (fwd P/E − 15)) + 25% dilution (6 − 5 × net share change %), each clamped 0–10 (D-020).
- Every number in the dossier must trace to a tool output; one repair retry on schema/grounding failure, then HOLD (D-012).
- Live (M2): Claude Opus 5.5 in a manual tool-use loop, one tool per step (parallel calls disabled), strict tool schemas, a required `reason` per call, finished by a `submit_dossier` tool; a failed grounding check is returned to the model as a tool error (D-032, D-033).
- Summarized reasoning streams as `agent_thought` events (partial and final) for Ava's thought bubble.
- Research-only journey ends after the dossier (no PM).

### 3.2 Portfolio Manager
- Input: `ResearchDossier` + `PortfolioSnapshot` when a fund is set (+ optional `risk_feedback`).
- Correlation haircut counts only stocks the fund actually holds; an empty fund has no overlap (D-027).
- LLM chooses action, limit and stop, and may ask Research one specific question. `size_position` (formula) sets shares and weight (D-006):
  weight = 5% × min(1, (conviction − 5) ÷ 4) × min(1, 45% ÷ realized vol) × (1 − 0.5 × max(0, max correlation − 0.6)), rounded to 0.1%; on a Risk Gate revision it is capped at 5% − existing weight − 0.5% (D-020).
- Output: `TradeIntent` (`action`, `ticker`, `target_weight_pct`, `dollar_amount`, `shares`, `limit_price`, `stop_loss_price`).
- Live (M2): one structured-output call (action, question, limit, stop, rationale). Code enforces price bounds: limit within ±2% of the latest price, stop 3–20% below the limit; otherwise HOLD (D-002).
- A Risk Gate resize and a resume after fund entry reuse the previous prices with no new LLM call (D-031).
- BUY floor (D-034): a BUY with conviction below the mandate's `min_buy_conviction` (default 6.0) becomes HOLD in code.

### 3.3 Risk Gate
- Checks (pure math): single name ≤ 5.0% NAV · settled cash sufficient · zero realized-loss collisions in trailing 30 days (wash sale) · marginal 99% 1-day VaR ≤ 2.5% NAV.
- Concentration, cash and VaR failures are **resizable** → back to PM once; wash-sale failure or a second failure → REJECTED.
- Output: `RiskCheckResult` (rule-by-rule observed vs. limit).

### 3.4 Founder approval (from M2.9, D-043)
- Shows exact shares, limit, dollars, stop, VaR before→after and a plain-English summary.
- Approval expires after 15 min or > 50 bps price drift → back to Risk Gate (D-013).
- Approvers: founder only (dashboard token; Slack user ID / phone allowlist in M6).

### 3.5 Execution Trader
- Verifies the order hash equals the approved `TradeIntent` hash before sending (D-013).
- Checks bid/ask spread, slices into 5 passive limit orders (TWAP), paper broker only, idempotent `client_order_id`.
- Market hours (D-025): an order approved while the market is closed is held; at the open the approval-expiry rule forces a fresh Risk Gate check before anything is sent.
- SELL orders (M3) follow the same path for positions the user holds.
- Output: `ExecutionReceipt` (avg fill, shares filled, fill %, commissions, slippage bps vs. arrival).

### 3.6 Portfolio Ledger
- Reconciles against broker positions, books a tax lot, updates cash and marks NAV to market.
- A mismatch with the broker blocks new trades until resolved.
- Reconciliation scope (D-025): the ledger is the book of record. Holdings entered at setup are tracked but not reconciled; positions Nexus opens through the paper broker are reconciled.
- SELLs (M3): lots close first-in-first-out; realized gains and losses are booked and feed the wash-sale rule.
- Output: `LedgerUpdate`.

## 4. Data contracts (Pydantic v2)

| Model | Key fields |
|---|---|
| `MicroActionEvent` | `run_id`, `agent_id` (Literal of 5 roles), `action_id`, `action_label`, `status` (IN_PROGRESS / COMPLETED / FAILED), `evidence_snippet`, `timestamp` (ISO-8601 UTC) |
| `HandoffSummary` | `signal`, `opinion` (1 sentence), `why_rationale` (1–2 sentences) |
| `PlainEnglish` | `headline`, `what_it_means`, `so_what` (D-007) |
| `ArtifactRef` | `agent_id`, `artifact_type`, `sha` (first 8 hex of sha256) |
| `HandoffRecord` | `run_id`, `seq`, `agent_id`, `status` (COMPLETED / FAILED / REJECTED / SKIPPED / AWAITING_FUND), timestamps, `consumed: list[ArtifactRef]`, `produced: ArtifactRef`, `output_type`, `output`, `handoff`, `plain`, `trigger`, `prompt_version`, `model`, `tokens`, `latency_ms`, and for LLM roles the split `llm_calls`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd` (D-004, D-044) |
| `ResearchDossier` | `ticker`, `bull_case`, `bear_case`, `base_score`, `llm_adjustment`, `adjustment_reason`, `conviction_score`, valuation, dilution, technicals, insider/institutional notes |
| `PortfolioSnapshot` | `nav`, `settled_cash`, positions with weights, `beta`, `current_var_pct` |
| `TradeIntent` | as 3.2; validators: shares × limit ≈ dollar_amount; BUY stop < limit |
| `Recommendation` | `action`, `ticker`, `target_weight_pct`, `limit_price`, `stop_loss_pct`: the PM's advice when no fund is set (D-021) |
| `FundConfig` | `cash`, `holdings[]` (ticker, shares, cost basis, acquired), `preset`, `mandate` (max % per name, max VaR %, target vol, resize buffer) |
| `RiskCheckResult` | `rules: list[RuleResult(name, passed, observed, limit, resizable)]`, `approved`, `hitl_status` |
| `ExecutionReceipt` | `arrival_price`, `avg_fill_price`, `shares_filled`, `fill_pct`, `commissions`, `slippage_bps`, `slices` |
| `LedgerUpdate` | `tax_lot`, `cash_before/after`, `nav_before/after`, `reconciled` |
| `FundGraphState` | `run_id`, `journey`, `ticker`, `portfolio` (optional: none until setup), artifacts (optional), `handoff_log` (append reducer), `agent_trace` (append reducer), `research_rounds`, `pm_attempts`, `risk_revisions`, `pm_question`, `risk_feedback`, `pm_route`, `risk_route` |

**R-TEL-1** Every sub-task emits `IN_PROGRESS` then `COMPLETED` or `FAILED` via `get_stream_writer()`.
**R-TEL-2** Each role, on finishing, emits a `HandoffRecord` (custom event) and appends it to `handoff_log`.
**R-TEL-3** Streaming uses `stream_mode=["updates", "custom"]`.
**R-TEL-4** With `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` set, every run is one LangSmith trace (D-044): graph nodes as chain spans; each Claude call as an `llm` span with the full prompt and response, token usage incl. cache read/write, the answering model, stop reason, latency, time to first token and cost; each registry tool as a `tool` span; each data-cache miss as a `fetch:<namespace>` span (SEC attempts and status) and cache hits counted on the tool span. Root traces carry `run_id`, `thread_id` (the first run of an approval resume or `/continue` chain), `user_id`, `ticker`, `journey` and policy-mode tags. Traces are flushed before the API response and the CLI exit. Unset = no tracing, no network.

## 5. Tool registry (D-006, D-017)

Data comes through one provider interface (`nexus/data/`, D-030): `fixture` (sample data, tests, no network) or `live` (SEC EDGAR XBRL facts, submissions, Form 4 XML and filing text; yfinance prices, valuation and holders), cached per day under `.cache/`. SEC requests carry `NEXUS_SEC_USER_AGENT` and stay under 10/s. R2 also reports annual operating cash flow vs net income and receivables growth. Missing facts are reported as n/a and score neutral (5.0) in the scorecard.

Single source of truth: `nexus/tools/registry.py`. No web search anywhere. Each tool carries `permission: read | write | irreversible`; no LLM role holds a write or irreversible tool (D-015). Every result carries `source` + `as_of`; same-day per-ticker cache.

| Role | Tools |
|---|---|
| Research | R1 `sec_list_filings` · R2 `sec_get_financials` · R3 `sec_get_filing_section` · R4 `sec_get_insider_trades` · R5 `get_institutional_holders` · R6 `get_cap_table` · R7 `get_valuation` · R8 `get_price_history` · R9 `compute_technicals` · R10 `get_earnings_transcript` (optional, paid key) · R11 `compute_scorecard` · `submit_dossier` |
| PM | P1 `get_portfolio_snapshot` · P2 `get_fund_mandate` · P3 `compute_correlation_beta` · P4 `compute_realized_vol` · P5 `size_position` |
| Risk | `check_concentration` · `check_cash_and_margin` · `check_wash_sale` · `compute_marginal_var` |
| Execution | `get_nbbo_quote` · `plan_twap_slices` · `submit_limit_order` (irreversible) · `poll_order_status` · `compute_slippage_bps` |
| Ledger | `get_broker_positions` · `reconcile_positions` · `book_tax_lot` (write) · `settle_cash` (write) · `mark_to_market_nav` |

Known data gaps: no free Level-2 (NBBO used); 13F is indexed by filer (yfinance holders used); transcripts need a paid key.

## 6. Plain-English layer (D-007)

- Every role produces a `PlainEnglish` explanation; it is display-only and never read by a downstream role.
- Roles 3–5 and all of M1: deterministic templates that convert % and bps into dollars.
- Roles 1–2: deterministic templates in M2 as well (D-029); LLM-written explanations are deferred until the show needs a richer voice.
- `nexus/glossary.yaml` defines jargon for UI hover tooltips. Plain is the default view; Pro shows the 3-line handoff.

## 7. Safety and security

- Paper trading only; endpoint fixed in code.
- Filing and transcript text is delimited as untrusted data in prompts (D-014).
- Per-run token budget enforced: 400k tokens per LLM role per run; reaching it stops the role and the run ends in HOLD. Timeouts and retries with backoff on every external call; SEC EDGAR User-Agent and ≤ 10 req/s.
- Model settings (D-032): `claude-opus-5-5`, adaptive thinking (summarized), effort `medium`, prompt caching on the system prompt, server-side refusal fallback (`fallbacks: "default"`). LLM text is clipped to the handoff contract limits.
- API binds to 127.0.0.1 with a bearer token from M4 (D-013).
- Orders use idempotent `client_order_id`.

## 8. Experience and UI (M5; design track D-008, D-024, D-026)

### 8a. The show (default experience)
Six screens, cinematic by default with **Skip to result** (a remembered "Quick" preference):
1. **Setup** (skippable): cash, optional holdings, Careful / Balanced / Bold.
2. **Search**: "What are you curious about?" — one search bar with ticker autocomplete and journey chips (Evaluate · Research · Can I add…? · Check my stocks).
3. **Agent floor**: five character cards in a row; the active agent enlarges and plays its scene:
   - **Ava · Research Analyst (AI)**: thought bubble with real reasoning, evidence board filling with documents and their key numbers, conviction meter and stamp.
   - Handoff: a case file slides along the link to the next agent.
   - **Marcus · Portfolio Manager (AI + formula)**: X-ray of the user's holdings with correlations highlighted, sizing dial.
   - **The Vault · Risk Gate (rules engine, no AI)**: four locks open one by one; a failure sounds an alarm and stamps SENT BACK; asks for the fund here if none is set.
4. **Your call**: full-screen order ticket, plain-English summary, 15-minute countdown, hold-to-approve, one-tap reject.
5. **Kai · Execution Trader (code)**: live fill tape and slippage badge. **Penny · Portfolio Ledger (code)**: receipt and fund-value counter.
6. **Mission report**: the run as a plain-English story with a timeline; Evaluate another / View portfolio.

Honesty rules (D-026): every animation maps to a real engine event (tool call, decision, handoff); no fake progress; M2 thinking time is filled with the agent's real streamed reasoning; reduced-motion users get simple fades. Deterministic roles are always labelled "no AI". Copy refers to agents by name or "they", never gendered pronouns.

### 8b. Header (D-024)
Plain labels by default — **Fund value · Today · Cash available · Invested** — with hover definitions from `nexus/glossary.yaml`; the Pro switch shows NAV · Daily P&L · Settled cash · Gross exposure.

### 8c. Mission Control and Portfolio (power-user views)
- Mission Control: left omnichannel feed (web, Slack, WhatsApp); center Agent Floor with live checklist (`✓ ⟳ ○ ✗`), `[⚡ Trigger Solo]`, handoff footer and handoff chips on links (D-005); right Received | Produced inspector, raw JSON, **approvals queue**; run-replay strip.
- Portfolio page: holdings, tax lots, cash history, run history.

### 8d. Prototypes and stack
- Design prototype (D-008): https://claude.ai/artifact/8Np5FD1fSuqBQv7VNKiH7q — the show (round 2) and Mission Control (round 1), replaying recorded runs exported by `design/export_runs.py`.
- Stack: Next.js + TypeScript, Tailwind + shadcn/ui, React Flow, Framer Motion, Recharts, TanStack Query, EventSource, TS types generated from OpenAPI.
- Observability: LangSmith, one trace per run with token and cost per Claude call; `LANGSMITH_TRACING`, `LANGSMITH_API_KEY` (tracing-only key), `LANGSMITH_PROJECT=nexus` set locally and on Vercel (R-TEL-4, D-044).

## 9. Milestones & progress

Status: ✅ done · ⏳ planned next · ○ not started. Update status and date when a milestone is accepted.

| # | Milestone | Status | Done | Scope | Accepted when |
|---|---|---|---|---|---|
| M0 | Design docs | ✅ | 2026-10-22 | REQUIREMENTS, DECISIONS, AGENT_FRAMEWORK, CLAUDE.md, shared doc + workflow diagram | User reviewed |
| M1 | Tracer bullet | ✅ | 2026-10-22 | Schemas, LangGraph spine with ReAct loop and feedback loops, fixture-backed tools, real scoring / sizing / risk math, handoff records, plain-English layer, CLI stream | 39 tests green; reference runs in §10 |
| D1 | Design round 1 | ✅ | 2026-10-22 | Mission Control prototype replaying recorded runs | User reviewed |
| R1 | Requirements refinement | ✅ | 2026-10-22 | Journeys, fund setup without invented money, the show, personas, architecture changes (D-021–D-026) | Docs + diagram updated |
| M1.5 | Optional fund in the engine | ✅ | 2026-10-22 | `FundConfig` + presets (`nexus/fund.py`), `fund_check`, `Recommendation`, `AWAITING_FUND`, CLI `--fund none\|sample\|file` + cash prompt, resume at the PM without re-research | 45 tests green; no-fund NVDA → BUY 4.2% advice → $100k entered → 29 sh, 4/4 pass, booked; `--fund sample` reproduces §10 |
| D2 | Design round 2 | ✅ | 2026-10-22 | Six-screen show prototype (`Show.dc.html`); Mission Control kept (`Main.dc.html`) | User reviewed |
| M2 | Live AI + data | ✅ | 2026-10-22 | Claude for Research + PM, EDGAR + yfinance provider with daily cache, journey router + `setup` / `research` / `what-if` commands, streamed reasoning, token budgets, eval harness (`evals/`, 25 tickers) | Evals: 100% completed (schema + grounding), prices pass sanity checks, stable actions over 3 reruns, conviction spread ≤ 1.0. Full run 2026-10-22 (25 × 3, `evals/results/2026-10-22-1440.json` + rerun `-1444.json` after fixes): completed 75/75, prices ok 75/75, conviction spread ≤ 1.0 25/25 (max 0.6), stable actions 21/25 — flips only at conviction 5.0–6.0; with the 6.0 BUY floor (D-034) re-scored 23/25 (CVX, PFE straddle 6.0); $6.83 |
| M2.5 | Private live deployment | ✅ | 2026-10-22 | Slim API (FastAPI: start run, live event stream, fund settings, run history), the show as an installable PWA (Next.js), single-user login, hosted frontend + backend + Postgres, live data, advice and simulated fills only (no real approvals yet) | Open the URL on your Android phone, install it, run "Evaluate NVDA" end to end; nobody else can sign in; API key never reaches the browser |
| M2.6 | Practice-mode messaging | ✅ | 2026-10-22 | PRACTICE badge, setup promises (no linking, no real money, private), practice labels, Trade Simulator / Practice Ledger roles, simulated-trade copy, mission report "act on it yourself" hand-off with copyable order, education-not-advice notes | Deployed; engine explanations reworded; 67 tests green |
| M2.7 | Research credibility pass | ✅ | 2026-10-22 | "Real research · simulated trades": SIMULATED TRADES badge, LIVE DATA badge, source label + link on every evidence tile (exact 10-Q/10-K on SEC EDGAR, Form 4 list, Yahoo pages), dossier `sources` + `reading_summary`, verdict-first mission report (action, sizing, conviction, bull/bear, why adjusted, sources) | Deployed; 69 tests green; NVDA 10-K link resolves |
| M2.8 | Home screen value story | ✅ | 2026-10-22 | Value headline ("Your AI research desk reads the filings so you don't have to."), what Ava and Marcus do, "How your desk works" strip (Ava → Marcus → The Vault) on the search screen | Deployed; reviewed at phone and desktop widths |
| M2.9 | Real approval pause | ⏳ | | `request_approval` + `hitl_approval` (`interrupt()`), Postgres checkpointer in Supabase, `POST /api/runs/{id}/approve`, 15-min / 0.5% expiry → fresh Vault check, "Your call" ticket (countdown, hold-to-approve, reject, decide later), home banner for pending approvals, CLI y/N (D-043) | A cleared trade waits for you; approve → filled & booked; reject → nothing traded; an expired approval goes back to The Vault; a pending approval survives closing the app |
| T1 | LangSmith telemetry | ✅ | 2026-10-23 | One LangSmith trace per run: node, `llm` (full prompt, token split incl. cache, cost, answering model, latency, first token), tool and data-fetch spans; cache writes priced apart; `HandoffRecord` token split + `cost_usd`; flush before response/exit (D-044, R-TEL-4) | 81 tests green; a live NVDA run shows one trace with per-call cost in LangSmith |
| M3 | Simulated money flow | ○ | | Simulator with market-hours awareness (no Alpaca, D-039), portfolio persists after each simulated trade, Decimal money, SELL path + FIFO + realized gains/losses, position monitor ("Check my stocks") | Ledger reconciles to the cent; a stop-loss hit produces a SELL proposal that waits for approval |
| M4 | API | ○ | | FastAPI + SSE, run manager, auth, approvals queue, watchlist CRUD + scan + morning schedule, fund / portfolio / run-history endpoints | All endpoints work; stream replays a past run; scan yields ranked approval cards |
| M5 | Web app | ○ | | The show, Mission Control, Portfolio page, plain/pro header | A live run plays end to end in the show; approval from "Your call" |
| M6 | Slack + WhatsApp | ○ | | Same journey commands and approvals by message (Bolt Socket Mode, Twilio) | "Evaluate NVDA" by text, approve by reply; web stays in sync |

## 10. M1 reference runs (D-010)

Portfolio: NAV $2,450,000 · settled cash $612,000 · beta 1.08 · MSFT 4.8%, AAPL 2.5%, JPM 3.5%, AMD 3.2%, XOM 2.9% · current VaR 1.9% · AAPL loss of $4,210 realized 2026-10-09. Run date 2026-10-21.

| Run | Path | Key numbers |
|---|---|---|
| NVDA | Agent picks R4 (insider sales) → R6 (dilution) → R3 (China risk) → BUY 4.0% → 4/4 pass → filled → booked | Conviction 8.1 + 0.5 = 8.6 · 689 sh @ 142.10 limit ($97,907) · stop 128.00 · VaR 2.1% · fill 141.944 vs arrival 141.96 (−1.1 bps) · cash → $514,200.58 · NAV → $2,450,073.03 |
| AMD | Fund already holds 3.2%; PM adds 2.7% → concentration FAIL (5.90%) → PM resizes to 1.3% (200 sh) → 4.49% → 4/4 pass → filled | Conviction 6.0 + 1.4 = 7.4 · two Risk Gate handoff records · NAV → $2,450,043.20 |
| AAPL | PM buys 1.7% (181 sh) → wash-sale FAIL (loss 12 days ago, not resizable) → REJECTED (3/4) | Execution and Ledger SKIPPED |
| NVDA `--fixture needs_more` | PM asks "last 4 quarters gross-margin trend" → Research runs once more → proceeds | `research_rounds` = 2 |
| NVDA `--fixture loop_forever` | PM keeps asking → second ask exceeds the research cap → HOLD | Risk, Execution, Ledger SKIPPED |

Reference runs use `--fund sample`. No-fund run: NVDA → BUY advice 4.2% of fund (no correlation trim, no holdings), stop 9.9% below the $142.10 limit → The Vault asks for cash → $100,000 entered → 29 sh ($4,120.90) → VaR 0.00% → 0.29% → 4/4 pass → booked.

M1 notes: R9 returns fixture indicators (computed from R8 bars in M2); the Execution Trader fills deterministically at or one tick inside the bid; NAV marks only the new lot (all positions from M3).
