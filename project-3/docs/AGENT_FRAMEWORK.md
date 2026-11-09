# Nexus Investment Engine — Agent Framework

Shareable version: https://claude.ai/artifact/1bx8f5K67gugFsXRiYNcc6

## Agent pattern

**A sequential pipeline with an embedded ReAct research agent, bounded LLM-decided feedback loops, and a human approval gate.**

A code router turns each command into one of five journeys; the roles then run in order and pass a typed, validated output to the next. Two roles use an LLM (Claude Opus 5.5) and make real decisions; three are plain code because they control the money and the books.

| Role | Type | What it decides |
|---|---|---|
| Ava · Research Analyst | ReAct agent (LLM) | Which follow-up tools to call, based on what it finds (up to 8 calls) |
| Marcus · Portfolio Manager | LLM + sizing formula | Buy, sell or hold (a BUY below conviction 6.0 becomes HOLD); or send a question back to Research (once) |
| The Vault · Risk Gate | Deterministic code (no AI) | Pass, reject, or send back to the PM to resize (once), capped by every failed rule |
| Kai · Trade Simulator | Deterministic code | Nothing; fills only the founder-approved order at live prices (simulated) |
| Penny · Portfolio Ledger | Deterministic code | Nothing; reconciles and books |

- **Why not a single ReAct agent:** one free-running loop would control sizing, risk checks and order placement. Those steps must be predictable and auditable, so they stay in code.
- **Why not multi-agent:** no role needs to negotiate with or supervise another. Handoffs carry typed records, not chat history.

## Workflow

```
Command → Journey router (code) ─┬ Evaluate / Research / Check my stocks ─▶ 1 Ava · Research (ReAct)
                                 └ What-if ("Can I add $50k?") ───────────▶ 3 The Vault (hypothetical order)
  1 Ava ◀── more data (once) ──┐
       Baseline (R2 R7 R8 R9 R11) → Think (LLM) → Act: call 1 tool + reason → [fixed read-only tools]
         ▲                         │ done                                        │ result
         └── think again ── Remember (write to run memory) ◀── Observe ◀─────────┘
                                   ▼        (loop ends when done or after 8 tool calls)
                             submit_dossier (schema + grounding; 1 repair, else HOLD)
       Research only ends here ──────────────────────────────▶ Mission report
  2 Marcus · PM ── HOLD ─────────────────────────────────────▶ Mission report
  Fund check (code) ── no fund: ask for cash │ advice only ──▶ Mission report
        ▲ resize (once)
  3 The Vault · Risk Gate ── rejected ───────────────────────▶ Mission report
  Your call · approval pause ── you reject ─────────────────▶ Mission report
        (expired or market closed → back to The Vault)
  4 Kai · Trade Simulator → 5 Penny · Ledger ──────────────────────▶ Mission report
Scan watchlist = one Evaluate run per ticker, each with its own approval.
Every step above is traced: LangSmith · one trace per run (each Claude call's prompt, tokens, cost;
every tool and data fetch timed; the approval resume joins the same thread).
```

## The one-liner

My agent helps **a solo fund founder** **research a stock and, when it makes sense, size, risk-check, execute and book a trade** in **an installable web app (Slack and WhatsApp planned)**, replacing **the 3–4 hours of reading SEC filings, building sizing spreadsheets, checking risk limits, placing orders and reconciling the books by hand, with mistakes that cost real money**. It **researches the company by choosing its own follow-up checks, proposes a sized trade, risk-checks it, executes it and books it** on its own using **a fixed set of 30 tools (no web search)**, hands off to a human **before any trade is simulated**, and I'll know it works when **the founder** can **go from "Evaluate NVDA" to a booked, reconciled simulated trade (or a clearly explained HOLD/REJECT)** in under **10 minutes** with **9 out of 10 runs finishing cleanly: no risk-rule breaches, every number traceable to its source data, and the ledger reconciling to the cent.**

## The framework

| Field | Fill in |
|---|---|
| **Agent goal** | Turn a ticker command into a researched, sized, risk-checked, founder-approved, simulated and booked trade, with every step's output visible. |
| **Where do people use it?** | An installable web app (PWA) for phone and desktop, hosted on Vercel and open only to the founder's email. Slack and WhatsApp are planned (M6). A command-line tool is used during development. |
| **What steps does it take, in order?** | 0. A code router picks the journey from the command (evaluate, research only, what-if, check my stocks, scan). 1. Ava (Research) gathers baseline data, then chooses follow-up checks. 2. Marcus (PM) decides buy, sell, hold or "need more research" (a BUY needs conviction 6.0 or more); a formula sizes it as a % of the fund. If no fund is set, the run asks for cash here or ends with advice. 3. Risk Gate runs 4 rule checks; a fixable failure goes back to the PM once, resized to fit every failed rule. 4. The run pauses; the founder approves or rejects. 5. The Trade Simulator fills the order in slices at live prices; no broker, no real money. 6. The Ledger checks its own records and books the trade. |
| **What can it actually do?** | Look up: (1) SEC filings and insider trades (SEC EDGAR), (2) market prices and valuation (yfinance), (3) the fund's portfolio and rules. Calculate, no side effects: (4) indicators, scores, position size, risk limits. Change something: (5) simulate orders at live prices (irreversible, approval required), (6) write to the fund's ledger (deterministic code only, never the LLM). |
| **What does it need to remember?** | Within a run: typed handoffs between steps, loop counters and the agent's tool-choice trail, saved by LangGraph's Postgres checkpointer when the run pauses for approval, so it can resume later. Across sessions: no chat memory; the user's fund settings (cash, holdings, risk preset) and run history are stored in Supabase Postgres. Saving positions after each trade arrives in M3. |
| **What should it never do?** | Never trade without founder approval, link a bank or brokerage, or move real money (trades are simulated, fixed in code). Never let the LLM set the final share count, place orders or write to the ledger. Never exceed the risk preset's limits for one stock and worst-day loss (careful 3% / 1.5%, balanced 5% / 2.5%, bold 8% / 4%). Never use web search or a tool outside the fixed list, follow instructions found in documents, or send an order that differs from the approved one. |
| **Human-in-the-loop** | One gate before the first irreversible action: the run pauses and shows the exact order (shares, limit, dollars, stop-loss, risk impact, plain-English summary). The graph pauses with LangGraph interrupt(), and the paused run is checkpointed in Supabase Postgres, so it survives closing the app. The founder holds to approve, rejects, or decides later on the "Your call" ticket (y/N in the CLI); only the owner's email can sign in. Approving after 15 minutes or a 0.5% price move sends the order back to the Risk Gate for a fresh check (at most 2 rechecks). |
| **What happens when something breaks?** | A data source failure retries with backoff, then shows as failed in the live checklist. Missing critical data means HOLD with a reason. Malformed LLM output gets one retry with the error shown to the model, then HOLD. Every loop has a hard limit, a retried order can't be filled twice, and a ledger mismatch blocks new trades until resolved. |
| **How do you see what it did and what it cost?** | Every run is one LangSmith trace when tracing is switched on. Each Claude call shows the full prompt and reply, tokens (including prompt-cache reads and writes), cost, the model that answered, and latency. Each tool and data fetch is timed. An approval resume joins its run in the same LangSmith thread. Each role's handoff also records its token split and cost in dollars; the first live check cost $0.09 for NVDA. |
| **How do you know it worked?** | Share of runs that reach a reconciled trade, or a justified HOLD/REJECT, in under 10 minutes with zero rule breaches and every number traceable to source data. Target 9 out of 10 on a fixed test set of 25 tickers. The first full eval (25 tickers × 3 runs, 22 Oct) completed 75 of 75 runs with grounded numbers; with the 6.0 BUY floor, 23 of 25 tickers got the same action every run. From November the evals replay frozen data and also test judgement: one fact is changed in a copy of a stock's data (heavy insider selling, a material weakness) to check that Ava notices and adjusts, Marcus is tested alone on made-up dossiers against his rules, and robustness cases cover tool failures and prompt injections (D-045). |

## How it meets the brief

| Criterion | How Nexus meets it |
|---|---|
| Decides what to do next | Research picks its own follow-up tools; the PM chooses to proceed, ask for more research, resize or drop the trade |
| Calls tools | The research agent selects and calls tools itself from a fixed, read-only list |
| Holds state across steps | Typed shared state with loop counters and a tool-choice trail, checkpointed in Postgres for pause and resume |
| Recovers from errors | Retries with backoff, one self-correction retry, resize after a failed risk check, HOLD when data is missing |
| Hands off to a human | A real pause for founder approval before any trade is simulated |

**The three rules, applied:**
- **Task completion, not single-shot accuracy:** success is measured on the whole chain, from command to a reconciled ledger.
- **State is the hard part:** each step's state is a typed record with fingerprints of what it received and produced; fund settings, run history and paused runs live in Postgres; no chat memory.
- **Write actions deserve a human:** reads and calculations run on their own; orders go through founder approval; ledger writes are made only by deterministic code that reconciles its own records.
