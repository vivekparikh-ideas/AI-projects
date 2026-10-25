"""Same-day disk cache so re-running a ticker on the same day sees identical inputs (D-006)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from langsmith import traceable

from nexus import tracing

# On Vercel only /tmp is writable: set NEXUS_CACHE_DIR=/tmp/nexus-cache there.
CACHE_ROOT = Path(os.environ.get("NEXUS_CACHE_DIR") or Path(__file__).resolve().parents[2] / ".cache")


def cached(namespace: str, key: str, fetch: Callable[[], Any]) -> Any:
    """Return today's cached JSON value for (namespace, key), fetching and storing it on a miss."""
    folder = CACHE_ROOT / date.today().isoformat() / namespace
    path = folder / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")
    if path.exists():
        tracing.count(f"cache_hits.{namespace}")  # counted on the tool span that asked; misses get their own span
        return json.loads(path.read_text())
    value = traceable(run_type="retriever", name=f"fetch:{namespace}", metadata={"key": key})(fetch)()
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return value
