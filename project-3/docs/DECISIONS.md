# Nexus Investment Engine — Decision Log

Append-only. Never delete an entry: mark it **Superseded by D-xxx** or **Amended by D-xxx** and add a new one.
Format: context → decision → rejected alternatives → consequences.

---

## D-001 Fixed LangGraph workflow, not multi-agent
- **Date:** 2026-10-21 · **Status:** Accepted, amended by D-018
- **Context:** Five roles with clear stages; capital at risk; need streaming and pause/resume.
- **Decision:** One LangGraph `StateGraph`; roles are nodes passing typed state.
- **Rejected:** Supervisor or multi-agent network (no named limit that justifies coordination cost); plain scripts (no checkpoint/interrupt).
- **Consequences:** Predictable control flow; LangGraph justified mainly by HITL resume and streaming.

## D-002 LLMs only in Research Analyst and Portfolio Manager
- **Date:** 2026-10-21 · **Status:** Accepted
- **Context:** Hallucination in sizing, risk or bookkeeping would cost money.
- **Decision:** Risk Gate, Execution Trader and Portfolio Ledger are deterministic Python forever.
- **Rejected:** LLM risk reviewer; LLM-assisted reconciliation.
- **Consequences:** Roles 3–5 are fully unit-testable.

## D-003 Deep Agents for Research Analyst
- **Date:** 2026-10-21 · **Status:** Superseded by D-006, then D-017
- **Context:** Research is open-ended; LangChain `deepagents` offers planning, scratch files and sub-agents.
- **Decision:** Use `create_deep_agent()` inside node 1 only.
- **Consequences:** Dropped: the user wanted a deterministic tool list; a planner was more than the task needs.

## D-004 HandoffRecord audit trail
- **Date:** 2026-10-21 · **Status:** Accepted
- **Context:** Founder wants to see exactly what each role received and produced.
- **Decision:** Every role emits a `HandoffRecord` with `consumed` / produced artifact hashes; persisted to SQLite from M3.
- **Rejected:** Reading checkpoints for history (awkward to query).
- **Consequences:** Handoff integrity is testable (consumed hash == upstream output hash).

## D-005 Handoff UX: chips on links + side panel
- **Date:** 2026-10-21 · **Status:** Accepted
- **Context:** A separate tab forces switching away from the live floor.
- **Decision:** Handoff chips on Agent Floor links; click → Received | Produced side panel; run-replay strip.
- **Rejected:** Separate Handoffs tab; tab + chips.
- **Consequences:** One screen for live and past runs.

## D-006 Fixed tool registry, no web search
- **Date:** 2026-10-21 · **Status:** Accepted; fixed-sequence part superseded by D-017
- **Context:** User wants a known tool list, not ad-hoc web search.
- **Decision:** `registry.py` maps each role to a fixed tool list; originally code ran R1–R9 in order. Position sizing is a formula (P5), not LLM judgment.
- **Rejected:** Web search tool; LLM-decided sizing.
- **Consequences:** Reproducible inputs; tool set auditable by test.

## D-007 Plain-English layer, default view
- **Date:** 2026-10-21 · **Status:** Accepted
- **Context:** Founder does not follow the financial jargon in handoffs.
- **Decision:** `PlainEnglish(headline, what_it_means, so_what)` per role; display-only; templates for deterministic roles; LLM text for roles 1–2 with number-grounding check; `glossary.yaml` tooltips; Plain default, Pro toggle.
- **Rejected:** Replacing financial handoffs; Pro as default.
- **Consequences:** Explanations cannot influence decisions.

## D-008 UI design track after M1; M5 stack
- **Date:** 2026-10-21 · **Status:** Accepted
- **Context:** Want a modern, high-tech, maintainable UI.
- **Decision:** Clickable prototype replaying recorded M1 runs, 2–3 rounds, lock tokens; M5 in Next.js + TS, Tailwind + shadcn/ui, React Flow, Framer Motion, Recharts, TanStack Query, EventSource, OpenAPI-generated types.
- **Rejected:** Design at M5 only.
- **Consequences:** Design iterates in parallel with M2–M4.

## D-009 HITL stub in M1, real interrupt in M3
- **Date:** 2026-10-21 · **Status:** Accepted
- **Context:** M1 places no real orders.
- **Decision:** M1 auto-approves with a visible stub; M3 adds a dedicated `hitl_approval` node using `interrupt()` so Risk Gate never re-runs on resume.
- **Consequences:** Real broker and real approval ship together in M3.

## D-010 M1 fixture numbers
- **Date:** 2026-10-21 · **Status:** Accepted, amended 2026-10-22 for D-018
- **Decision:** NVDA happy path; TSLA reject → resize → pass; AAPL wash-sale hard reject; NVDA `needs_more` loop. Numbers in REQUIREMENTS §10.

## D-011 Project location and runtime
- **Date:** 2026-10-21 · **Status:** Accepted
- **Decision:** `AI projects/project-3/` with its own Python 3.12 venv (shared venv is 3.15, too new for reliable wheels).

## D-012 Evals and self-correction for LLM steps
- **Date:** 2026-10-21 · **Status:** Accepted (architecture review); eval design amended by D-045
- **Decision:** Golden set of 20–30 tickers with code graders (schema, every number grounded, decision stable across 3 reruns). On schema/grounding failure: one retry with the error fed back, then HOLD. No LLM critic.

## D-013 Execution and approval safety
- **Date:** 2026-10-21 · **Status:** Accepted (architecture review)
- **Decision:** Order hash must match approved intent; approval expires after 15 min or > 50 bps drift; idempotent `client_order_id`; API on 127.0.0.1 with bearer token from M4; approvals allowlisted to the founder.

## D-014 Untrusted content and budgets
- **Date:** 2026-10-21 · **Status:** Accepted (architecture review); amended by D-044 (cost is now measured per run; only the token cap is enforced)
- **Decision:** Filing/transcript text delimited as data in prompts; read-only tools for LLM roles; per-run token/cost cap; timeouts and retries on external calls; missing critical data → HOLD.

## D-015 Tool permission labels and trace fields
- **Date:** 2026-10-21 · **Status:** Accepted (architecture review); amended by D-044 (token split and cost added)
- **Decision:** Registry entries carry `permission`; test asserts no LLM role holds write/irreversible tools. `HandoffRecord` carries `prompt_version`, `model`, `tokens`, `latency_ms`. State keeps only `handoff_log` (no duplicate handoffs dict).

## D-016 Scorecard-based conviction
- **Date:** 2026-10-21 · **Status:** Accepted
- **Context:** LLM scores drift between runs; conviction drives sizing.
- **Decision:** `R11 compute_scorecard` (valuation, trend, dilution, insider) sets `base_score`; LLM may adjust by ±1.5 with a required reason.
- **Rejected:** LLM sets the score alone.

## D-017 Research Analyst as a bounded ReAct agent
- **Date:** 2026-10-22 · **Status:** Accepted; supersedes D-006's fixed sequence (registry stays)
- **Context:** Course brief requires an agent that decides what to do next and calls tools; a fixed sequence fails that.
- **Decision:** Code runs a baseline (R2, R8, R9, R11); then a LangGraph tool-calling loop lets the LLM pick follow-ups from its fixed read-only registry, each with a `reason`; cap 8 calls + token budget; ends with `submit_dossier`.
- **Rejected:** Deep Agents (planner and sub-agents not needed); keeping the fixed sequence.
- **Consequences:** Tool calls vary by company; evals must check grounding and stability. MINT note: justified by the stated requirement and real variance in research depth.

## D-018 Bounded LLM-decided feedback loops
- **Date:** 2026-10-22 · **Status:** Accepted; amends D-001
- **Decision:** PM may send one question back to Research; a resizable Risk Gate failure (concentration, cash, VaR) returns to the PM once with the failed rule; wash-sale, a second failure or PM HOLD ends the run. Counters `research_rounds`, `risk_revisions` in state.
- **Rejected:** Unbounded loops; LLM in the Risk Gate.
- **Consequences:** Demonstrates recovery; Risk Gate stays deterministic.

## D-019 Rename to Nexus Investment Engine
- **Date:** 2026-10-22 · **Status:** Accepted
- **Decision:** The product is named **Nexus Investment Engine** (was "Apex AI Fund"); the Python package is `nexus/` (was `apex/`). Earlier entries are kept as written.

## D-020 M1 implementation refinements
- **Date:** 2026-10-22 · **Status:** Accepted; amends D-010, D-016, D-017
- **Context:** Writing M1 against the real scoring and sizing math showed two planned scenarios could not happen honestly.
- **Decision:**
  - The concentration-breach scenario uses **AMD** (an add-on to the fund's existing 3.2% position), not TSLA: the sizing formula never proposes more than 5% on its own, and TSLA's own figures would score a HOLD.
  - AAPL's starting weight is **2.5%** (was 4.1%) so the wash-sale rule is its only failure.
  - The research baseline adds **R7 valuation**, which the scorecard needs; insider activity stays out of the scorecard and is weighed by the LLM adjustment.
  - Scorecard and sizing formulas are fixed as written in REQUIREMENTS §3.1–3.2.
  - Early exits run a `finalize` step that records unreached roles as SKIPPED.
- **Consequences:** All four reference runs are produced by the real formulas, not hard-coded results.

## D-021 Manual, skippable fund setup with no invented money
- **Date:** 2026-10-22 · **Status:** Accepted
- **Context:** The prototype showed fund figures nobody had entered; a hypothetical $100k default would confuse users.
- **Decision:** A setup screen collects cash, optional holdings and a risk preset (Careful / Balanced / Bold → mandate). Setup can be skipped; then Research and the PM run without a fund (PM gives a % recommendation) and `fund_check` asks for cash just before the Risk Gate, or the user takes advice only.
- **Rejected:** Sync from the Alpaca paper account; a hypothetical $100k fund; mandatory setup.
- **Consequences:** Portfolio becomes optional state; new `Recommendation` artifact and `AWAITING_FUND` status; mandate moves from a constant into fund settings.

## D-022 Default mode: always go to approval
- **Date:** 2026-10-22 · **Status:** Accepted
- **Decision:** Every BUY or SELL that passes the Risk Gate waits for the user's approval. An advice-only mode exists only for runs without a fund.
- **Rejected:** Advice-only by default with trading opt-in.

## D-023 Five user journeys in the MVP
- **Date:** 2026-10-22 · **Status:** Accepted
- **Decision:** Evaluate, Research only, What-if, Watchlist scan, Position monitor (with SELLs), plus a Portfolio page. A deterministic `journey_router` parses commands; scan is an orchestrator running one Evaluate per ticker.
- **Rejected:** An LLM router (no named need — MINT); evaluate-only MVP.
- **Consequences:** SELL path, FIFO lots and realized P&L move into M3; watchlist and approvals queue into M4.

## D-024 Plain header labels with a Pro toggle
- **Date:** 2026-10-22 · **Status:** Accepted
- **Decision:** Fund value · Today · Cash available · Invested by default; NAV · Daily P&L · Settled cash · Gross exposure under Pro; hover definitions from the glossary.

## D-025 Market hours and reconciliation scope
- **Date:** 2026-10-22 · **Status:** Accepted
- **Decision:** Orders approved while the market is closed are held and re-checked by the Risk Gate at the open. With manual setup the ledger is the book of record; only positions Nexus opened through the paper broker are reconciled against it.

## D-026 The show: cinematic experience with named agents
- **Date:** 2026-10-22 · **Status:** Accepted
- **Context:** Starting a dense dashboard on submit felt flat; the user wants it to feel like real agents working for them.
- **Decision:** Six screens (setup → search → agent floor → your call → fills and booking → mission report); personas Ava, Marcus, The Vault, Kai, Penny; whole floor visible with the active agent enlarged; cinematic by default with Skip to result.
- **Honesty rules:** every animation maps to a real engine event; no fake progress; deterministic roles labelled "no AI"; no gendered pronouns in copy.
- **Rejected:** Spotlight-and-dock staging; role names only; quick-by-default.
- **Consequences:** Presentation is a separate layer on the same event stream; personas live only in UI config; M2 streams Ava's reasoning text.

## D-027 Correlation haircut counts only stocks the fund holds
- **Date:** 2026-10-22 · **Status:** Accepted; amends D-020's sizing formula
- **Context:** M1 trimmed NVDA for its 0.71 correlation with AMD even when the fund held no AMD, which mattered once funds became user-entered.
- **Decision:** `compute_correlation_beta` returns the overlap only if the most-correlated stock is held; an empty fund has none. Sample-fund numbers are unchanged because it holds AMD and MSFT.
- **Consequences:** No-fund and cash-only NVDA size at 4.2% (not 4.0%).

## D-028 Design direction locked
- **Date:** 2026-10-22 · **Status:** Accepted
- **Decision:** The show (six screens, named agents, whole-floor staging, cinematic with Skip) and the Mission Control look (dark grid, Inter + JetBrains Mono, violet = AI, amber = you decide, slate = code, cyan = live) are approved as the M5 target.
- **Consequences:** M5 implements `design/` prototypes in Next.js; further visual changes go through a new design round.

## D-029 Plain-English stays template-based in M2
- **Date:** 2026-10-22 · **Status:** Accepted; amends D-007
- **Decision:** Explanations for Ava and Marcus keep using `nexus/explain.py` templates built from the validated artifacts, instead of LLM-written text.
- **Rejected:** LLM-written explanations with a second grounding check (more moving parts, more tokens, no observed need yet).
- **Consequences:** Explanations are always consistent with the numbers; revisit when the M5 show needs a richer voice.

## D-030 Data provider abstraction
- **Date:** 2026-10-22 · **Status:** Accepted
- **Decision:** All tools read data through `nexus/data` (`fixture` | `live`). Live = SEC EDGAR (companyfacts XBRL frames, submissions, Form 4 XML, filing HTML) + yfinance, cached per day. Risk math takes volatility and correlation as inputs instead of reading data itself.
- **Consequences:** Tests stay offline and deterministic; `--live` swaps the source without touching node code.

## D-031 Resize and resume reuse prices
- **Date:** 2026-10-22 · **Status:** Accepted
- **Decision:** After a resizable Risk Gate failure, or when the user enters a fund after advice, Marcus keeps the previous action, limit and stop (including the exact stop price) and only the formula re-sizes.
- **Consequences:** No extra LLM call; the order the user sees cannot drift between advice and ticket.

## D-032 Model and API settings
- **Date:** 2026-10-22 · **Status:** Accepted
- **Decision:** `claude-opus-5-5`; adaptive thinking with summarized display (feeds Ava's thought bubble); effort `medium`; system prompt cached; streaming; server-side refusal fallback (`server-side-fallback-2026-07-01`, `fallbacks: "default"`); 400k-token budget per role per run; filing text wrapped in `<tool_output>` as untrusted data.
- **Consequences:** About $0.07–0.15 per evaluate run (Ava ≈ 15–20k tokens, Marcus ≈ 2k). Effort can be tuned per role once the full eval exists.

## D-033 Manual tool-use loop for Ava
- **Date:** 2026-10-22 · **Status:** Accepted
- **Context:** The SDK tool runner owns the loop; Nexus needs one telemetry event per Think/Act/Remember step, its own caps and the grounding check between submit and acceptance.
- **Decision:** The research node drives the loop; the Claude policy makes one call per Think step with one tool allowed (`disable_parallel_tool_use`), strict schemas, `tool_choice: auto` (forced tool use is not available on Opus 5.5) and a nudge if no tool is called.
- **Consequences:** Identical loop for scripted and Claude policies; tests cover caps and repairs offline.

## D-034 BUY floor at conviction 6.0
- **Date:** 2026-10-22 · **Status:** Accepted
- **Context:** Full eval (25 × 3): every decision flip (META, JPM, PFE, AVGO) happened at conviction 5.0–6.0, where the formula sizes only 0.4–1.2% of the fund. No ticker at ≥ 6.0 flipped. Conviction varies ≤ 0.6 between runs.
- **Decision:** Mandate field `min_buy_conviction` (default 6.0). Marcus is told the floor; code converts any BUY below it to HOLD.
- **Rejected:** Floor at 5.5 (keeps borderline flips); leaving it to the model (21/25 stable).
- **Consequences:** Re-scored eval 23/25 stable; CVX and PFE straddle 6.0, as any cutoff will for scores within run-to-run noise. AAPL, NFLX, AVGO, META, JPM and CVX's sub-6.0 runs become HOLD. Configurable per fund.

## D-035 Eval-driven fixes
- **Date:** 2026-10-22 · **Status:** Accepted
- **Decision:** From the first full eval: net-income fallback tags and None-safe evidence (AVGO crash), retries on network errors (NFLX timeout), transcript tool removed from Ava's list until a data source exists (16 wasted calls), eval `repaired` metric counts failed submissions only.

## D-036 Private live deployment before M3, as an installable web app
- **Date:** 2026-10-22 · **Status:** Accepted
- **Context:** The user wants a live version on their Android phone. Nexus is a local CLI; a hosted backend and a mobile-ready screen are needed.
- **Decision:** First live version is **private (the user only)**, delivered as a **PWA** (install from Chrome; Play Store via Trusted Web Activity later from the same code), deployed **before M3** as milestone M2.5: slim M4 API + M5 show + hosting + single-user login, live data, advice and simulated fills.
- **Rejected:** Invite-only or public first (needs multi-user isolation, licensed market data, legal review of investment-advice rules, quotas); native app (separate codebase); M3 before deployment.
- **Consequences:** M4 and M5 shrink to what is left after M2.5. Before any other user: per-user data isolation, licensed market data (yfinance is personal-use only), disclaimers and legal review, usage caps.

## D-037 Hosting: Vercel Services + Supabase
- **Date:** 2026-10-22 · **Status:** Accepted
- **Decision:** One Vercel project with Services (Beta): `web` (Next.js PWA) and `api` (FastAPI via `main.py`), `/api/*` → api. Each run streams inside one request (Hobby allows 300 s; runs take 30–90 s), so nothing lives in server memory. Supabase Postgres stores funds and runs (pooled connection, RLS on with no public policies); Supabase Auth email magic link; the backend verifies each token with Supabase and allows only `NEXUS_OWNER_EMAILS`. Caches go to `/tmp`.
- **Rejected:** Neon + separate auth (user chose one vendor); a container host for the backend (not needed at these durations); in-memory run state (scale-to-zero and multiple instances).
- **Consequences:** M3's approval pause will resume through the stored state (LangGraph Postgres checkpointer) rather than an open request. Risk: Yahoo may throttle cloud IPs; fallback is licensed market data.

## D-038 Practice mode: Nexus never touches real accounts or money
- **Date:** 2026-10-22 · **Status:** Accepted; refines D-021 and D-026
- **Context:** The user's intent: people explore how they could allocate cash to a new stock given their current portfolio, without linking banks or brokerages. The app's wording ("Bought all shares", "fund value") implied real trading.
- **Decision:** Position Nexus as a practice tool everywhere: "practice portfolio", PRACTICE badge, setup promises (no linking ever, no real money, private), Kai = Trade Simulator, Penny = Practice Ledger, simulated-trade wording, and a mission-report hand-off: "place the order yourself in your own brokerage app" with copyable order details. Education-not-advice notes on search and report.
- **Consequences:** Clearer trust story and lighter regulatory footprint (still not legal advice; review before any public release).

## D-039 No broker integration (drop Alpaca)
- **Date:** 2026-10-22 · **Status:** Accepted; supersedes the Alpaca parts of the M3 plan, D-013 and D-025
- **Context:** Alpaca paper trading is also simulated money; its value is realism and a path to real trading, which the practice product does not need.
- **Decision:** Keep Nexus's own simulator (live prices); M3 adds market-hours awareness to it. Reconciliation remains an internal consistency check of the practice ledger.
- **Rejected:** Alpaca paper (extra account and keys for realism nobody needs); Interactive Brokers paper (needs a gateway server).
- **Consequences:** No broker keys anywhere; M3 is the approval pause plus sells and monitoring inside the practice portfolio.

## D-040 Real research, simulated trades
- **Date:** 2026-10-22 · **Status:** Accepted; refines D-038
- **Context:** Practice-mode wording risked making the research look like a toy; the research is real (SEC filings, Form 4s, live market data, grounded numbers) and is the product's value.
- **Decision:** "Practice" applies to money and trades only. Badge reads SIMULATED TRADES; Ava's stage shows LIVE DATA; every evidence item and the dossier carry source labels and links to the exact filing or page; the mission report leads with the research verdict (action, % of portfolio, conviction, bull/bear, adjustment reason, what Ava read, sources) and puts the simulated trade below it.
- **Consequences:** Visible provenance is the basis for later paid features (track record, alerts, shareable reports); still education, not advice (D-036, D-038).

## D-041 Resizes respect every failed rule
- **Date:** 2026-10-22 · **Status:** Accepted; fixes D-018 / D-020 sizing
- **Context:** Found while recording a promo: with $100k cash plus AMD and MSFT, The Vault failed the worst-day-loss (VaR) rule; Marcus re-submitted the same 25 shares because the revision cap only handled concentration, and the UI said "Resized".
- **Decision:** The revision cap is the minimum over the failed resizable rules: concentration (limit − held − buffer), cash (settled cash), VaR (the largest addition keeping VaR just under the limit, from `var_headroom_pct`, the inverse of the marginal-VaR formula). No headroom → HOLD immediately with the reason. A revision that doesn't shrink the trade becomes HOLD; "Resized" only appears when the size actually fell.
- **Consequences:** Tests cover the headroom maths, a VaR failure that resizes and passes, and a no-headroom HOLD with a single Risk Gate check.

## D-042 One word for the money: "simulated"
- **Date:** 2026-10-22 · **Status:** Accepted; supersedes the wording in D-038 and D-040 (the positioning stands)
- **Decision:** User-facing copy says "simulated" for trades and nothing for the money itself: Portfolio value · Cash · Invested in the header (the SIMULATED TRADES badge carries the meaning); setup headline "See what your research desk would do with your portfolio."; Penny is the Portfolio Ledger; "Simulated trade complete."; footer "Trades are simulated: no accounts linked, no real money moves." No copy mentions a broker (D-039).

## D-043 The real approval pause ships before the rest of M3
- **Date:** 2026-10-22 · **Status:** Accepted; implements D-009 and D-013, replaces the M1 auto-approve stub
- **Context:** The user wanted the approval step back in the app before M3's sells, portfolio persistence and monitor. Until now The Vault passed every cleared trade straight to Kai with a "passed automatically" banner.
- **Decision:** Two graph nodes between The Vault and Kai. `request_approval` fixes an `ApprovalTicket` (order, limit, stop, checks, worst-day loss, price and time at issue) in state. `hitl_approval` pauses with LangGraph `interrupt()`. It is split from the ticket step because a resume re-runs the node from its start, so the issue time must already be saved. Approve after 15 minutes or a price move over 0.5% sends the order back to The Vault for a fresh check and a new ticket (at most 2 rechecks), and reject ends the run with nothing traded. The paused run is saved by LangGraph's Postgres checkpointer in Supabase (`thread_id` = run id, written once at the pause, with the Nexus contract types allowlisted for deserialization); the local API and CLI keep it in memory. API: the stream ends with `awaiting_approval` + `run_finished` carrying the ticket; `POST /api/runs/{id}/approve {decision}` resumes on the same run row. App: a "Your call" ticket on The Vault's stage with a live countdown, hold-to-approve (1.2 s) and one-tap reject, "Decide later", and a home-screen banner for runs waiting on you. CLI: asks y/N; `--approve yes|no` answers without asking, and a non-terminal run rejects. Tests, evals and design exports pass `configurable.approval = "auto"`; the API never does.
- **Rejected:** Ending the run and re-entering at Kai from saved JSON, as the fund card does (simpler, but not a real pause and skips the checkpointer the course brief asks for); a per-step checkpoint (about 20 network writes per run to Supabase for no benefit).
- **Consequences:** Every simulated trade now waits for the user's explicit approval. M3 keeps the SELL path, portfolio persistence, market hours and the position monitor.

## D-044 LangSmith for tokens, cost and debugging
- **Date:** 2026-10-22 · **Status:** Accepted; amends D-014 and D-015
- **Context:** The user wanted to see token usage, cost and debugging data per run. Usage was read on every call but stored as one `tokens` total per role; cost existed only in evals; cache writes were priced as plain input; there was no tracing.
- **Decision:** LangSmith is the single place to view it, with full prompts and responses. LangGraph traces nodes natively. `llm.stream()` is a manual `@traceable(run_type="llm")` span because langsmith 0.14's `wrap_anthropic` patches `beta.messages.create`/`parse` but not `beta.messages.stream`, the call Nexus makes. The span reports `usage_metadata` in LangSmith's shape (cache tokens added into input, 5m/1h writes split out) and `ls_model_name` = the model that answered, so LangSmith prices server-side fallbacks correctly (it knows Opus 5.5 pricing). `registry.call()` wraps every tool in a `tool` span; `cached()` opens a `fetch:` span on a miss and counts hits on the calling span. `Usage` keeps cache writes apart (priced at $5/MTok, 1.25× input) and `HandoffRecord` carries the split and `cost_usd`. Traces flush in a `finally` before the SSE response ends (Vercel freezes the function after) and at CLI exit.
- **Rejected:** An in-app admin view and a per-call Postgres table (a second copy of what LangSmith shows; may come later for cross-run cost per fund); a "View trace" link per run (building the URL needs a key with `projects:read`, and the deployed key is tracing-only by choice; find a run in LangSmith by its `run_id` metadata instead); `wrap_anthropic` (does not cover the streaming beta call); a per-run contextvar for `Usage` (each policy already owns its `Usage`; only the eval runner reads the process-wide `SESSION`, one run at a time).
- **Consequences:** Prompts, SEC excerpts and fund figures leave the system for LangSmith when tracing is on. Tracing is off unless the env vars are set, so tests stay offline. A per-run dollar cap (D-014) is now easy to add but is not enforced yet.

## D-045 Evals on frozen snapshots with planted signals
- **Date:** 2026-11-05 · **Status:** Accepted; amends D-012
- **Context:** The M2 harness checked plumbing (completed, decided, prices ok, stable) on live data. It could not tell whether Ava's adjustment was justified, whether her tool choices fit the evidence or whether Marcus followed his own rules, and live data drifts between runs, so a moved score could come from the market or the prompt. Every M2 run of AVGO and NFLX used the same three follow-up tools, which might be habit rather than investigation; nothing could tell.
- **Decision:** Evals replay **frozen snapshots**: `evals/record.py` asks the live provider every question a run can ask (all tool arguments) and saves the answers per ticker; a `snapshot` provider (`nexus/data/snapshot.py`) replays them behind the existing provider interface, so the real tool code still runs. A missing key raises and is logged, and the run is INVALID (never a silent live fallback). Four suites in `evals/cases.py`, the single source of truth, exported to `evals/golden_cases.csv`: **regression** (unchanged snapshot, Ava → Marcus, no fund), **planted signals** (one fact changed in a copy: insider selling, insider buying, a material-weakness risk factor, weak cash quality, a doubled buyback; none touches a scorecard input, so the base score is fixed and Ava's median adjustment is compared with the same ticker's unchanged control), **robustness** (tool error, missing section, two prompt injections, empty insider data, missing gross margin, two second-round PM questions) and **Marcus alone on synthetic dossiers** (floor at 5.9 / 6.1, SELL only when held, question rules, price bands at $4.20 and $1,250.37, a custom floor, an injection), graded on his **raw** answer before code checks it. Graders are code only; a check with no rule yet is REVIEW for the user. 3 reruns per case by default, compared by median; `--quick` runs P1 cases once. A hard `--budget` cap stops new runs. Each run writes a results JSON with provenance (model, prompt versions, snapshot and case-file hashes) and an HTML report compared with an accepted baseline (NEW FAIL / FIXED). Phase 1 covers 5 tickers (NVDA, JPM, KO, TSLA, PFE); Phase 2 adds the other 20 as regression cases only. `ClaudePMPolicy.last_raw` keeps the model's answer and the BUY floor moved into `apply_buy_floor()`, shared by the node and the evals; behaviour is unchanged.
- **Rejected:** An LLM judge for bull/bear and rationale quality (the user chose code plus manual review for now); grading on future returns (noisy and unfair); 10 reruns (about 3× the cost for little gain); more tickers for judgement tests (5 different company types show a pattern; more tickers mainly add data-shape coverage, which Phase 2 regression gives); freezing at the tool level instead of the data level (would skip the tool code and make planted changes hand-edited in two places).
- **Consequences:** Phase 1 is 60 cases, about $11.50 for a full run (3 reruns) and about $2–3 for `--quick`; data costs nothing. Run `pytest` on every change; run the paid evals when a prompt, tool list or description, model or effort, the input format, the dossier fields or the grounding/sanity checks change, and before accepting a prompt version. Re-record snapshots rarely (quarterly, or when data code changes) and re-run the full set after, since re-recording resets the baseline. Thresholds are first guesses to tune after the first run. Recording showed two data issues the evals will surface: JPM's operating cash flow is already negative (normal for a bank), so the weak-cash change is not a clear negative there; and TSLA's base score is 1.0, so an adjustment below −1.0 makes conviction negative, which fails dossier validation and forces a repair. Both are caught by the offline checks (below).
- **Addendum (2026-11-05, user request):** Evals are split into **offline checks** (free, no model: snapshot coverage, planted inputs visible to Ava and pointing the intended way, code guards, synthetic dossiers; `--offline`, run on any change) and **online evals** (Claude, paid). Every online run does the offline checks first as a preflight and stops before any model call if a snapshot cannot serve every call. The report shows the two as separate parts so a failure is easy to place: inputs and code, or model judgement.
- **Addendum (2026-11-05):** SIG-JPM-4 (weak cash quality at JPM) is removed. A bank's operating cash flow is already negative (lending runs through it; JPM −$147.8B), so setting it to 40% of net income made JPM look healthier, the opposite of the planted signal. `cases.EXCLUDED` lists such pairs and both the online cases and the offline checks skip them. Phase 1 is 59 cases.

## D-046 Conviction stays inside 0–10
- **Date:** 2026-11-05 · **Status:** Accepted; amends D-016
- **Context:** The offline eval checks (D-045) found that TSLA's base score is 1.0. Ava may adjust by −1.5, which gave conviction −0.5; the dossier schema requires 0–10, so the dossier failed validation, used up its one repair and could end the run with no result. Any stock with a base under 1.5 (or over 8.5) could hit it, in the app as well as in evals.
- **Decision:** `conviction_from()` in `nexus/tools/research.py` computes base + adjustment and stops it at 0 and at 10. Ava's adjustment is kept as she gave it (still within ±1.5); only the final conviction is bounded.
- **Rejected:** Narrowing the allowed adjustment per stock (makes the prompt depend on the base score); leaving it and letting the eval report the failure.
- **Consequences:** Ava can always submit a strongly negative view of a weak stock. A very weak stock's conviction reads 0.0, below every buy floor. The offline conviction-range check now confirms the bound for every snapshot.
- **Addendum (2026-11-05, after the quick run):** Planted cases ask only for the move Ava can still make before her ±1.5 limit (a control at −1.2 needs only −0.3 more; with under 0.1 of room the check is REVIEW). PM-02 (conviction 6.1) passes on BUY or HOLD; the floor itself is tested by PM-03. SELL rule for PM-05: limit between 2% below spot and spot (graded only; Marcus's prompt and the code sanity check still bound BUY prices only). Offline coverage also fails a snapshot whose latest financials are more than 4 quarters old.

- **Addendum (2026-11-06, user confirmed; bar for one serious signal lowered to 0.2 later that day, see below):** The planted-signal bars stay: a serious red flag (insider selling spike, weak cash quality) must move Ava's adjustment by at least 0.3; the Risk Factors flag (SEC investigation and material weakness) by at least 0.5; insider buying by at least +0.3. Why: the controls wobble by up to 0.2 between reruns, so a smaller move cannot be told apart from noise; 0.3 is enough to change a decision near the 6.0 buy floor; and it is a fifth of Ava's ±1.5 range. Known gap: Ava's prompt (ava-v1) gives no scale for the adjustment, so the next prompt version should state the same scale the eval checks.
- **Addendum (2026-11-06, user decision after the ava-v2 run):** The bar for one serious signal (insider selling, insider buying, weak cash) is lowered from 0.3 to **0.2**; the risk-factor red flag stays at 0.5 and the buyback band at −0.1…+0.7. Why: with ava-v2, four cases named the signal in every run and moved 0.2 (NVDA-1, NVDA-4, KO-1, KO-4). The bars are now one constant each (`SIGNAL_BAR`, `FLAG_BAR`); the report reads its wording from them. Trade-off accepted: a 0.2 median move is the size of the largest control spread, so the eval is less able to tell a small reaction from rerun wobble. `--regrade` re-scored the stored runs for free: baseline 45 → 48/59 (JPM-1, KO-1, TSLA-1 now pass).

## D-047 Bank revenue tag
- **Date:** 2026-11-05 · **Status:** Accepted; fixes R2 (D-030)
- **Context:** The quick eval run showed Ava saying in every JPM run that "the formula's growth and dilution inputs come from a stale CY2014Q3 XBRL tag". JPM stopped tagging `Revenues` in 2014 and reports `RevenuesNetOfInterestExpense`, which R2 did not know, so revenue growth (+4.9%), net share change (+0.6%) and the base score (4.6) came from Q3 2014. Ava compensated with adjustments of +1.2 to +1.5, which also left no room for planted signals.
- **Decision:** Add `RevenuesNetOfInterestExpense` to the revenue tags (the most recent tag still wins). JPM now reads CY2026Q3: revenue $50.17B, growth +8.1%, net shares −3.1%. The offline checks fail any snapshot whose financials are more than 4 quarters old.
- **Consequences:** JPM's snapshot was re-recorded (sha 481d18dc). Other banks (BAC in Phase 2) get the same fix; the offline check catches any other company whose tags go stale.


## D-048 Ava prompt v2: an adjustment scale and always reading risk factors
- **Date:** 2026-11-06 · **Status:** Accepted 2026-11-09 by the founder (full run 2026-11-06-1911, 55/58 after review, is the new baseline)
- **Context:** The Phase 1 baseline showed Ava naming planted red flags in every run but moving her adjustment only 0–0.25, and never opening Risk Factors for JPM or KO. ava-v1 gave her the ±1.5 range but no scale, so the eval's bars (D-045 addendum 2026-11-06) existed only in the test.
- **Decision:** `ava-v2` adds (1) a scale: about 0–0.2 for nothing material, 0.3–0.7 for one serious signal, 0.5–1.5 for a material red flag or several serious signals; a serious signal left near 0 must be explained in `adjustment_reason`; operating cash flow is not an earnings-quality signal for banks and lenders; (2) in a first investigation, always read the latest risk factors before submitting (round-2 questions are unchanged). The scale names kinds of evidence, not the planted values. Loop caps unchanged (D-018).
- **Rejected:** Lowering the eval bars to match v1; a code rule that forces the adjustment (the judgement stays Ava's, D-016).
- **Consequences:** One more tool call per first investigation (cost ~+10%). Watch the buyback case (must not overreact) and control stability.
- **Also (2026-11-06):** PM-14's synthetic dossier scales diluted shares with the price so market cap stays as recorded (Marcus rightly refused a $4.20 KO with KO's share count); an offline check enforces it. `report.py --review <run> CASE=PASS|FAIL` records the founder's verdict on REVIEW cases in the results file (the case keeps `review.was`); ROB-08, PM-08 and PM-17 were passed and 2026-11-05-2248 accepted as the baseline (45/59).
- **Result (2026-11-06, runs 2026-11-06-1721 and -1726, $5.62):** planted signals 16/29 → 23/29. Risk factors now read in every run (JPM 0/15 → 15/15, KO 3/18 → 18/18, TSLA 9/18 → 18/18); JPM 1/2/3/5, KO-3, TSLA-1/3/4 fixed. Still under the bar: insider selling at NVDA and KO (−0.2), weak cash at NVDA (−0.2) and KO (−0.1), insider buying at PFE (+0.1); new fail PFE-5 (buyback −0.2, allowed −0.1). Controls stay steady (spread ≤ 0.2). Regression, robustness and Marcus suites not yet re-run on v2.
- **Bug found by this run (amends D-046):** `ResearchDossier`'s validator still expected base + adjustment unclamped, so a dossier at a 0 floor (TSLA base 1.0, adjustment −1.2) was rejected and Ava produced no dossier. The validator now applies the same 0–10 clamp; a test covers it.
- **Regraded at the 0.2 bar (2026-11-06):** ava-v1 planted signals 19/29, ava-v2 26/29 (counting TSLA-3 from run -1726). Still failing on v2: KO-4 weak cash (−0.1), PFE-2 insider buying (+0.1), PFE-5 buyback (−0.2, allowed −0.1).
- **PM-14 removed (2026-11-06, user decision):** a low-priced version of a real company contradicts what Marcus knows about it, so he refuses to trade (correctly) whatever the share count. Price-band rules stay covered by PM-13 and the offline guards. Phase 1 is 58 cases (78 in all); ids are not renumbered.
- **Full Phase 1 on ava-v2 (run 2026-11-06-1911, $8.63 incl. a $0.52 rerun):** 52/58 pass, 3 fail, 3 REVIEW, against ava-v1's 48/58 (regraded on today's graders). Regression 5/5, robustness 7/7 + ROB-08 REVIEW, Marcus 14/14 + PM-08/PM-17 REVIEW (same behaviour as the cases passed in the baseline), planted 26/29. Fails: NVDA-4 weak cash (−0.1), KO-1 insider selling (−0.1, passed in v1 at −0.2), PFE-2 insider buying (+0.1). The run went past 15 hours with the machine asleep: SIG-NVDA-C/3/4/5 hit API read timeouts and were rerun (run 2026-11-07-1110) and merged, recorded in provenance `merged`. ROB-05's grader treated "insiders had no sales and no buys" as an invented insider story; the "data is empty" phrases now include no/0 sales, buys and purchases (test added).
- **Accepted (2026-11-09):** founder passed ROB-08, PM-08 and PM-17 on the v2 run and accepted it as the baseline (55/58). ava-v2 is the live research prompt.

