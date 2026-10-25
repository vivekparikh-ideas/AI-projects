# Nexus Investment Engine

An all-agent paper-trading fund: a ReAct research agent and an LLM portfolio manager propose trades; a deterministic risk gate, execution trader and ledger control the capital. Design: [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) · [docs/DECISIONS.md](docs/DECISIONS.md) · [docs/AGENT_FRAMEWORK.md](docs/AGENT_FRAMEWORK.md).

**Status: Milestone 2.** Claude (Opus 5.5) drives Ava and Marcus on live SEC EDGAR and yfinance data with `--live`; fixture mode runs offline for tests. Broker and database arrive in M3.

## Setup
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Live setup
`.env` (git-ignored) needs `ANTHROPIC_API_KEY` and `NEXUS_SEC_USER_AGENT="Nexus Research you@example.com"`.

```bash
python run_cli.py setup                                    # your cash, holdings, risk preset → fund.yaml
python run_cli.py --ask "Evaluate NVDA" --live             # ≈ $0.10 per run
python run_cli.py --ask "Research TSLA" --live             # Ava only, nothing traded
python run_cli.py --ask "Can I add \$50k of AMD?" --live   # The Vault checks a hypothetical order
python evals/run_evals.py --tickers NVDA,KO --reruns 1     # eval smoke test; full set needs --yes
```

## Web app (M2.5)
```bash
# terminal 1: API on live data, dev user (no sign-in), local JSON store
set -a; source .env; set +a; NEXUS_DEV_USER=owner-local .venv/bin/uvicorn nexus.api.app:app --port 8765
# terminal 2: the show
cd web && NEXUS_API_URL=http://localhost:8765 NEXT_PUBLIC_NEXUS_DEV_AUTH=1 npx next dev -H 0.0.0.0
```
Production: https://nexus-investment-engine.vercel.app (deploy with `npx vercel deploy --prod` from this folder; Git is not connected).
Deploy: `vercel.json` defines two services (`web`, `api`); set the variables from `.env.example` in the Vercel project.

## Run (fixtures, no API cost)
```bash
pytest -q                                          # 60 tests
python run_cli.py --ticker NVDA                    # no fund: advice, then asks for your cash
python run_cli.py --ticker NVDA --fund sample      # $2.45M sample fund (reference runs)
python run_cli.py --ticker NVDA --pro              # 3-line financial handoffs
python run_cli.py --ticker AMD --fund sample                     # risk fail → PM resizes → passes
python run_cli.py --ticker AAPL --fund sample                    # wash-sale hard reject
python run_cli.py --ticker NVDA --fund sample --fixture needs_more    # PM sends a question back to Research
python run_cli.py --ticker NVDA --fund sample --fixture loop_forever  # loop cap → HOLD
python run_cli.py --ticker NVDA --show-payloads    # handoff records + full outputs
python run_cli.py --ticker NVDA --json > runs/nvda.jsonl  # raw stream for the design prototype
```

## Layout
```
nexus/
  schemas.py   state.py   telemetry.py   graph.py   render.py
  policies.py          # scripted decisions for the 2 LLM roles (Claude replaces these in M2)
  explain.py  glossary.yaml   mock_data.py
  tools/   registry.py research.py pm.py risk.py execution.py ledger.py
  nodes/   research_analyst.py portfolio_manager.py risk_gate.py execution_trader.py portfolio_ledger.py finalize.py
tests/
```
