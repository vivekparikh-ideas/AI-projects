"""Session bookkeeping: one LangGraph thread per browser session, deleted after 24 hours (decision #4)."""
import sqlite3
import time
import uuid

from gapfinder.config import SESSIONS_DB

MAX_AGE_HOURS = 24


def _connect() -> sqlite3.Connection:
    SESSIONS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SESSIONS_DB)
    conn.execute("CREATE TABLE IF NOT EXISTS session_index (thread_id TEXT PRIMARY KEY, created_at REAL NOT NULL)")
    return conn


def new_thread() -> str:
    thread_id = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute("INSERT INTO session_index VALUES (?, ?)", (thread_id, time.time()))
    return thread_id


def purge(max_age_hours: float = MAX_AGE_HOURS) -> int:
    """Delete saved progress for sessions older than max_age_hours. Returns how many were removed."""
    cutoff = time.time() - max_age_hours * 3600
    with _connect() as conn:
        old = [r[0] for r in conn.execute("SELECT thread_id FROM session_index WHERE created_at < ?", (cutoff,))]
        if not old:
            return 0
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        marks = ",".join("?" * len(old))
        for table in ("checkpoints", "writes"):  # tables created by LangGraph's SqliteSaver
            if table in tables:
                conn.execute(f"DELETE FROM {table} WHERE thread_id IN ({marks})", old)
        conn.execute(f"DELETE FROM session_index WHERE thread_id IN ({marks})", old)
    return len(old)
