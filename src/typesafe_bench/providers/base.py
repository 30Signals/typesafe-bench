from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunResult:
    model_name: str
    ticket_id: str
    latency_s: float
    input_tokens: int | None
    output_tokens: int | None
    answers: dict[str, Any] | None
    cached_input_tokens: int | None = None
    raw_usage: dict[str, Any] | None = field(default=None)
    error: str | None = None


def extract_cached_tokens(usage_dict: dict[str, Any] | None) -> int | None:
    """Best-effort read of a 'cached tokens' figure out of a provider's raw
    usage payload. Field names/nesting differ across APIs (OpenAI-style
    `prompt_tokens_details.cached_tokens`, Anthropic-style
    `cache_read_input_tokens`, etc.), so check the known shapes rather than
    assuming one schema."""
    if not usage_dict:
        return None

    direct_keys = (
        "cached_tokens",
        "cache_read_input_tokens",
        "cache_read_tokens",
        "prompt_cache_hit_tokens",
    )
    for key in direct_keys:
        if usage_dict.get(key) is not None:
            return usage_dict[key]

    for nested_key in ("prompt_tokens_details", "input_tokens_details"):
        nested = usage_dict.get(nested_key)
        if isinstance(nested, dict) and nested.get("cached_tokens") is not None:
            return nested["cached_tokens"]

    return None


class Provider:
    """Common interface: run one ticket's set of questions in a single call."""

    name: str

    def run(self, ticket_id: str, state: str, questions: dict[str, Any]) -> RunResult:
        raise NotImplementedError
