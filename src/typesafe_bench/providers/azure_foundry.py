from __future__ import annotations

import json
import time
from typing import Any

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

from .base import Provider, RunResult, extract_cached_tokens
from .common import REQUEST_TIMEOUT_S, SYSTEM_PROMPT, normalize_endpoint, strip_json_fences


class AzureFoundryProvider(Provider):
    """Generic adapter for any model deployed on a shared Azure AI Foundry
    resource, reached via the unified azure-ai-inference ChatCompletionsClient.
    Works the same way regardless of whether the deployment is a GPT or Claude
    model -- each model under benchmark is just a deployment name on the same
    endpoint/key."""

    def __init__(self, name: str, deployment: str, endpoint: str, api_key: str):
        self.name = name
        self.deployment = deployment
        self._client = ChatCompletionsClient(
            endpoint=f"{normalize_endpoint(endpoint)}/models",
            credential=AzureKeyCredential(api_key),
            connection_timeout=10,
            read_timeout=REQUEST_TIMEOUT_S,
        )

    def run(self, ticket_id: str, state: str, questions: dict[str, Any]) -> RunResult:
        # Static content (instructions + question definitions, identical on
        # every call for this task) goes in the system message, which is a
        # stable prefix across all tickets. Only the variable ticket text
        # goes in the user message. This ordering matters: prefix-based
        # prompt caching (OpenAI's automatic caching, Anthropic's
        # cache-control breakpoints) only helps the portion of the request
        # that is byte-identical from the start -- putting the ticket text
        # first, as an earlier version of this code did, would have broken
        # the shared prefix and made every call effectively uncached.
        system_prompt = (
            f"{SYSTEM_PROMPT}\nQuestions (JSON):\n{json.dumps(questions, indent=2)}"
        )
        user_prompt = f"Ticket:\n{state}"
        messages = [
            SystemMessage(content=system_prompt),
            UserMessage(content=user_prompt),
        ]

        start = time.perf_counter()
        try:
            response = self._client.complete(
                messages=messages,
                model=self.deployment,
                response_format="json_object",
            )
            latency = time.perf_counter() - start
            usage = getattr(response, "usage", None)
            total_prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            output_tokens = getattr(usage, "completion_tokens", None) if usage else None
            raw_usage = _usage_to_dict(usage)
            cached_input_tokens = extract_cached_tokens(raw_usage)
            # OpenAI-style `prompt_tokens` includes the cached portion as a
            # subset (unlike Anthropic, where cache tokens are reported
            # separately from input_tokens) -- normalize so `input_tokens`
            # always means "new, full-price" tokens across every provider,
            # which is what runner.cost_usd assumes.
            input_tokens = (
                total_prompt_tokens - (cached_input_tokens or 0)
                if total_prompt_tokens is not None
                else None
            )
            raw = response.choices[0].message.content
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
    """azure-ai-inference usage objects vary by underlying model provider
    (OpenAI-style vs. Anthropic-style fields); dump whatever shape comes back
    so downstream code (and the raw CSV) can inspect it rather than losing it."""
    if usage is None:
        return None
    for method_name in ("as_dict", "to_dict"):
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
