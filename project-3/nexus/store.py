"""Persistence for the hosted app (D-036): the user's fund and their run history.

`PostgresStore` (Supabase Postgres, via DATABASE_URL) in production; `JsonStore` for local dev and tests.
Runs are saved whole when they finish or pause, including the final graph state so an advice-only run can be
continued after the user enters cash. A run paused for approval is saved again (same id) when it resumes.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from nexus.fund import FundConfig


class Store(Protocol):
    def get_fund(self, user_id: str) -> FundConfig | None: ...
    def put_fund(self, user_id: str, fund: FundConfig) -> None: ...
    def delete_fund(self, user_id: str) -> None: ...
    def save_run(self, user_id: str, run: dict[str, Any]) -> None: ...
    def list_runs(self, user_id: str, limit: int = 30) -> list[dict[str, Any]]: ...
    def get_run(self, user_id: str, run_id: str) -> dict[str, Any] | None: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


SUMMARY_FIELDS = ("id", "command", "journey", "ticker", "outcome", "awaiting_fund", "awaiting_approval", "created_at", "parent_id")


class JsonStore:
    """One JSON file; fine for a single local user."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text()) if self.path.exists() else {"funds": {}, "runs": {}}

    def _save(self, db: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(db, default=str))

    def get_fund(self, user_id: str) -> FundConfig | None:
        raw = self._load()["funds"].get(user_id)
        return FundConfig(**raw) if raw else None

    def put_fund(self, user_id: str, fund: FundConfig) -> None:
        with self._lock:
            db = self._load()
            db["funds"][user_id] = fund.model_dump()
            self._save(db)

    def delete_fund(self, user_id: str) -> None:
        with self._lock:
            db = self._load()
            db["funds"].pop(user_id, None)
            self._save(db)

    def save_run(self, user_id: str, run: dict[str, Any]) -> None:
        with self._lock:
            db = self._load()
            runs = db["runs"].setdefault(user_id, {})
            created = runs.get(run["id"], {}).get("created_at")  # a resumed run keeps its place in history
            runs[run["id"]] = {**run, "created_at": created or run.get("created_at") or _now()}
            self._save(db)

    def list_runs(self, user_id: str, limit: int = 30) -> list[dict[str, Any]]:
        runs = sorted(self._load()["runs"].get(user_id, {}).values(), key=lambda r: r["created_at"], reverse=True)
        return [{k: r.get(k) for k in SUMMARY_FIELDS} for r in runs[:limit]]

    def get_run(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        return self._load()["runs"].get(user_id, {}).get(run_id)


SCHEMA = """
create table if not exists nexus_funds (
  user_id uuid primary key,
  config jsonb not null,
  updated_at timestamptz not null default now()
);
create table if not exists nexus_runs (
  id text primary key,
  user_id uuid not null,
  parent_id text,
  command text not null,
  journey text not null,
  ticker text not null,
  outcome text not null,
  awaiting_fund boolean not null default false,
  events jsonb not null,
  final_state jsonb not null,
  created_at timestamptz not null default now()
);
alter table nexus_runs add column if not exists awaiting_approval boolean not null default false;
alter table nexus_runs add column if not exists entry text;
create index if not exists nexus_runs_user_created on nexus_runs (user_id, created_at desc);
-- Only the backend's database role touches these tables; RLS with no policies blocks the public API.
alter table nexus_funds enable row level security;
alter table nexus_runs enable row level security;
"""


class PostgresStore:
    """Supabase Postgres through a pooled connection string (transaction mode works: no session state)."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._psycopg = psycopg
        self.dsn = dsn
        with self._conn() as c:
            c.execute(SCHEMA)

    def _conn(self):
        return self._psycopg.connect(self.dsn, autocommit=True, prepare_threshold=None)

    def get_fund(self, user_id: str) -> FundConfig | None:
        with self._conn() as c:
            row = c.execute("select config from nexus_funds where user_id = %s", (user_id,)).fetchone()
        return FundConfig(**row[0]) if row else None

    def put_fund(self, user_id: str, fund: FundConfig) -> None:
        from psycopg.types.json import Jsonb

        with self._conn() as c:
            c.execute(
                "insert into nexus_funds (user_id, config) values (%s, %s) "
                "on conflict (user_id) do update set config = excluded.config, updated_at = now()",
                (user_id, Jsonb(fund.model_dump())),
            )

    def delete_fund(self, user_id: str) -> None:
        with self._conn() as c:
            c.execute("delete from nexus_funds where user_id = %s", (user_id,))

    def save_run(self, user_id: str, run: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        with self._conn() as c:
            c.execute(
                "insert into nexus_runs (id, user_id, parent_id, command, journey, ticker, outcome, awaiting_fund, awaiting_approval, entry, events, final_state) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "on conflict (id) do update set outcome = excluded.outcome, awaiting_fund = excluded.awaiting_fund, "
                "awaiting_approval = excluded.awaiting_approval, events = excluded.events, final_state = excluded.final_state "
                "where nexus_runs.user_id = excluded.user_id",
                (run["id"], user_id, run.get("parent_id"), run["command"], run["journey"], run["ticker"], run["outcome"],
                 run["awaiting_fund"], run.get("awaiting_approval", False), run.get("entry"), Jsonb(run["events"]), Jsonb(run["final_state"])),
            )

    def list_runs(self, user_id: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                f"select {', '.join(SUMMARY_FIELDS)} from nexus_runs where user_id = %s order by created_at desc limit %s",
                (user_id, limit),
            ).fetchall()
        return [dict(zip(SUMMARY_FIELDS, (str(v) if isinstance(v, datetime) else v for v in row))) for row in rows]

    def get_run(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute(
                f"select {', '.join(SUMMARY_FIELDS)}, entry, events, final_state from nexus_runs where user_id = %s and id = %s",
                (user_id, run_id),
            ).fetchone()
        if not row:
            return None
        keys = (*SUMMARY_FIELDS, "entry", "events", "final_state")
        return {k: (str(v) if isinstance(v, datetime) else v) for k, v in zip(keys, row)}


def from_env() -> Store:
    dsn = os.environ.get("DATABASE_URL")
    return PostgresStore(dsn) if dsn else JsonStore(os.environ.get("NEXUS_STORE_FILE", "runs/store.json"))
