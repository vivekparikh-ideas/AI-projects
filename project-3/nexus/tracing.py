"""LangSmith tracing helpers (D-044). Tracing runs only when LANGSMITH_TRACING=true and LANGSMITH_API_KEY are set;
otherwise every helper here is a no-op, so tests and offline runs never touch the network."""

from __future__ import annotations

from typing import Any

from langsmith.run_helpers import get_current_run_tree


def annotate(**metadata: Any) -> None:
    """Add metadata to the span that is currently open (an LLM call, a tool, a data fetch)."""
    run = get_current_run_tree()
    if run is not None:
        run.add_metadata(metadata)


def count(key: str) -> None:
    """Increment a counter on the open span, e.g. data-cache hits seen inside one tool call."""
    run = get_current_run_tree()
    if run is not None:
        meta = (run.extra or {}).get("metadata", {})
        run.add_metadata({key: meta.get(key, 0) + 1})


def run_config(*, run_id: str, journey: str, ticker: str, thread_id: str | None = None, user: str | None = None,
               parent_id: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
    """LangGraph config keys that name and label the run's root trace. `thread_id` groups an approval resume
    or a /continue with the run it came from in the LangSmith Threads view."""
    return {
        "run_name": f"nexus:{journey}:{ticker}",
        "tags": [journey, *(tags or [])],
        "metadata": {"run_id": run_id, "thread_id": thread_id or run_id, "parent_id": parent_id, "user_id": user,
                     "ticker": ticker, "journey": journey},
    }


def flush() -> None:
    """Block until queued traces are sent. Serverless functions can freeze as soon as the response ends."""
    from langchain_core.tracers.langchain import wait_for_all_tracers

    wait_for_all_tracers()
