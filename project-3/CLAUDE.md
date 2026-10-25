# Nexus Investment Engine — instructions for Claude

Read `docs/REQUIREMENTS.md` (what to build) and `docs/DECISIONS.md` (why) before changing anything. They override defaults.

## Hard rules
- Build one milestone at a time. After each, give the test command and expected output, then wait for the user's "NEXT".
- No LLM in `risk_gate`, `execution_trader` or `portfolio_ledger` (D-002).
- No tool outside `nexus/tools/registry.py`; no web search (D-006, D-017). LLM roles get read-only tools only (D-015).
- Every loop keeps its cap: research agent ≤ 8 tool calls, PM→Research ≤ 1, Risk→PM ≤ 1 (D-018).
- No order without founder approval; paper broker only (D-009, D-013).
- Every sub-task emits a `MicroActionEvent`; every role emits a `HandoffRecord` with `PlainEnglish` (D-004, D-007).
- Plain-English text is display-only; never feed it to a downstream role.

## When something changes
- Update `REQUIREMENTS.md` in place.
- When a milestone is accepted, update its row in REQUIREMENTS §9 (status + date).
- Add a new entry to `DECISIONS.md`; mark old entries superseded or amended, never delete them.
- Keep `docs/AGENT_FRAMEWORK.md` and the shared doc (https://claude.ai/artifact/1bx8f5K67gugFsXRiYNcc6) consistent with the design.

## Environment
- Python 3.12 venv at `.venv` (`python3.12 -m venv .venv`); not the parent folder's 3.15 venv.
- Run tests: `pytest -q` (offline, fixture data). Live runs (`--live`, `evals/`) cost API tokens: ask before running the full eval set. Run a pipeline: `python run_cli.py --ticker NVDA` (no fund) or `--fund sample`.
