from __future__ import annotations

import json
import time
from typing import Any

import anthropic

from .base import Provider, RunResult, extract_cache_write_tokens, extract_cached_tokens
from .common import SYSTEM_PROMPT, normalize_endpoint, strip_json_fences


class AzureAnthropicProvider(Provider):
    """Adapter for Claude models deployed on Azure AI Foundry.

    Foundry only exposes Claude through the native Anthropic Messages API at
    <endpoint>/anthropic -- NOT the OpenAI-style Chat Completions API that
    AzureFoundryProvider/azure-ai-inference use (that returns a 404
    'api_not_supported' for Claude deployments). So this talks to that route
    directly with the official `anthropic` SDK, using the same Azure
    resource endpoint/key as everything else in models.yaml.

    This also means Claude is the one model family here where prompt caching
    is opt-in rather than automatic: the static system prompt (instructions +
    question definitions, identical across every ticket) is marked with an
    explicit `cache_control` breakpoint so the *first* call writes it to
    cache (`cache_creation_input_tokens`) and subsequent calls read it back
    at a discount (`cache_read_input_tokens`, surfaced here as
    cached_input_tokens).
    """

    def __init__(self, name: str, deployment: str, endpoint: str, api_key: str):
        self.name = name
        self.deployment = deployment
        self._client = anthropic.Anthropic(
            base_url=f"{normalize_endpoint(endpoint)}/anthropic", api_key=api_key
        )

    def run(self, ticket_id: str, state: str, questions: dict[str, Any]) -> RunResult:
        system_prompt = f"{SYSTEM_PROMPT}\nQuestions (JSON):\n{json.dumps(questions, indent=2)}"

        start = time.perf_counter()
        try:
            response = self._client.messages.create(
                model=self.deployment,
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": f"Ticket:\n{state}"}],
            )
            latency = time.perf_counter() - start
            usage = getattr(response, "usage", None)
            raw_usage = _usage_to_dict(usage)
            input_tokens = getattr(usage, "input_tokens", None) if usage else None
            output_tokens = getattr(usage, "output_tokens", None) if usage else None
            cached_input_tokens = extract_cached_tokens(raw_usage)
            cache_write_tokens = extract_cache_write_tokens(raw_usage)
            raw = "".join(
                block.text for block in response.content if getattr(block, "type", None) == "text"
            )
            try:
                answers = json.loads(strip_json_fences(raw))
            except (json.JSONDecodeError, TypeError):
                return RunResult(
                    model_name=self.name,
                    ticket_id=ticket_id,
                    latency_s=latency,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_input_tokens=cached_input_tokens,
                    cache_write_tokens=cache_write_tokens,
                    raw_usage=raw_usage,
                    answers=None,
                    error=f"non-JSON response: {raw!r}",
                )
            return RunResult(
                model_name=self.name,
                ticket_id=ticket_id,
                latency_s=latency,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
                cache_write_tokens=cache_write_tokens,
                raw_usage=raw_usage,
                answers=answers,
            )
        except Exception as exc:  # noqa: BLE001 - record and keep benchmarking
            latency = time.perf_counter() - start
            return RunResult(
                model_name=self.name,
                ticket_id=ticket_id,
                latency_s=latency,
                input_tokens=None,
                output_tokens=None,
                answers=None,
                error=str(exc),
            )


def _usage_to_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    for method_name in ("model_dump", "as_dict", "to_dict"):
        method = getattr(usage, method_name, None)
        if callable(method):
            try:
                return method()
            except Exception:  # noqa: BLE001
                pass
    try:
        return dict(vars(usage))
    except TypeError:
        return None
