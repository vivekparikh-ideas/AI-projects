"""Thin Claude client for the two LLM roles (D-002): streaming, adaptive thinking, refusal fallback,
prompt caching, an enforced per-run token budget (D-014) and a LangSmith span per call (D-044)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic
from langsmith import traceable

from nexus import tracing

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_TOKENS = 16000
RUN_TOKEN_BUDGET = 400_000  # input + output tokens across one role's calls in one run
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # on a policy refusal the API retries on a fallback model

_client: anthropic.Anthropic | None = None
# Prices per million tokens for MODEL. Cache writes (5-minute TTL, the only one used) cost 1.25x input.
PRICE_PER_MTOK = {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00}


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=3, timeout=180.0)
    return _client


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Usage:
    """Accumulated cost of one role's calls in one run; enforced against RUN_TOKEN_BUDGET."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    budget: int = RUN_TOKEN_BUDGET
    models: set[str] = field(default_factory=set)

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens

    def add(self, u: Any, model: str) -> None:
        self.calls += 1
        self.input_tokens += u.input_tokens
        self.output_tokens += u.output_tokens
        self.cache_read_tokens += u.cache_read_input_tokens or 0
        self.cache_write_tokens += u.cache_creation_input_tokens or 0
        self.models.add(model)

    def check(self) -> None:
        if self.tokens >= self.budget:
            raise BudgetExceeded(f"token budget reached ({self.tokens:,} of {self.budget:,})")


SESSION = Usage(budget=10**12)  # everything this process has spent; evals report it


def usage_metadata(u: Any) -> dict[str, Any]:
    """One call's usage in LangSmith's shape, so it prices the call. Anthropic reports cache tokens on top of
    input_tokens (not inside it), so they are added back into input_tokens; mirrors langsmith's Anthropic wrapper."""
    details: dict[str, int] = {}
    if u.cache_read_input_tokens:
        details["cache_read"] = u.cache_read_input_tokens
    split = getattr(u, "cache_creation", None)
    if split is not None:
        for key in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"):
            if getattr(split, key, 0):
                details[key] = getattr(split, key)
    elif u.cache_creation_input_tokens:
        details["cache_creation"] = u.cache_creation_input_tokens
    input_tokens = u.input_tokens + sum(details.values())
    out: dict[str, Any] = {"input_tokens": input_tokens, "output_tokens": u.output_tokens, "total_tokens": input_tokens + u.output_tokens}
    if details:
        out["input_token_details"] = details
    return out


def _trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """The full prompt as sent (system, messages, tools, schema); the budget object and callback stay out.
    `messages` is copied because the research policy keeps appending to the same list after this call."""
    kept = {k: v for k, v in inputs.items() if k not in ("usage", "on_thinking")}
    return {"model": MODEL, **kept, "messages": list(kept.get("messages") or [])}


def _trace_outputs(message: Any) -> dict[str, Any]:
    return message.model_dump(mode="json", exclude_none=True)


@traceable(run_type="llm", name="claude.messages", process_inputs=_trace_inputs, process_outputs=_trace_outputs,
           metadata={"ls_provider": "anthropic", "ls_model_name": MODEL})
def stream(
    *,
    system: str,
    messages: list[dict[str, Any]],
    usage: Usage,
    tools: list[dict[str, Any]] | None = None,
    output_format: dict[str, Any] | None = None,
    on_thinking: Callable[[str], None] | None = None,
    effort: str = EFFORT,
) -> Any:
    """One streamed Messages call. Returns the final message; `on_thinking` receives summarized reasoning as it arrives."""
    usage.check()
    params: dict[str, Any] = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": effort, **({"format": output_format} if output_format else {})},
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
    }
    if tools:
        params["tools"] = tools
        params["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}  # one tool per Think step
    started = time.monotonic()
    first_token_ms = None
    with client().beta.messages.stream(**params) as s:
        for event in s:
            if event.type == "content_block_delta":
                if first_token_ms is None:
                    first_token_ms = int((time.monotonic() - started) * 1000)
                if on_thinking and event.delta.type == "thinking_delta":
                    on_thinking(event.delta.thinking)
        message = s.get_final_message()
    for target in (usage, SESSION):
        target.add(message.usage, message.model)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    usage.latency_ms += elapsed_ms
    call = Usage()
    call.add(message.usage, message.model)
    tracing.annotate(
        ls_model_name=message.model,  # the model that answered: a server-side fallback is priced as itself
        usage_metadata=usage_metadata(message.usage), stop_reason=message.stop_reason, fallback_used=message.model != MODEL,
        effort=effort, latency_ms=elapsed_ms, first_token_ms=first_token_ms, cost_usd=round(cost_usd(call), 6),
        role_tokens_used=usage.tokens, role_token_budget=usage.budget,
    )
    return message


def cost_usd(u: Usage) -> float:
    p = PRICE_PER_MTOK
    return (u.input_tokens * p["input"] + u.output_tokens * p["output"] + u.cache_read_tokens * p["cache_read"]
            + u.cache_write_tokens * p["cache_write"]) / 1e6


def text_of(message: Any) -> str:
    return "".join(b.text for b in message.content if b.type == "text")


def thinking_of(message: Any) -> str:
    return " ".join(b.thinking for b in message.content if b.type == "thinking" and b.thinking).strip()
