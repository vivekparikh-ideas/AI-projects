import sqlite3
import time

from gapfinder.agent import sessions


def test_purge_removes_only_old_sessions(tmp_path, monkeypatch):
    db = tmp_path / "sessions.sqlite"
    monkeypatch.setattr(sessions, "SESSIONS_DB", db)
    old, fresh = sessions.new_thread(), sessions.new_thread()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE checkpoints (thread_id TEXT, data TEXT)")
        conn.executemany("INSERT INTO checkpoints VALUES (?, 'x')", [(old,), (fresh,)])
        conn.execute("UPDATE session_index SET created_at = ? WHERE thread_id = ?", (time.time() - 25 * 3600, old))

    assert sessions.purge() == 1
    with sqlite3.connect(db) as conn:
        left = {r[0] for r in conn.execute("SELECT thread_id FROM checkpoints")}
    assert left == {fresh}
