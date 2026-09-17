from __future__ import annotations

import json
import time
from typing import Any

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

from .base import Provider, RunResult, extract_cached_tokens

_SYSTEM_PROMPT = """\
You are a structured-decision engine. You will be given the content of a support
ticket and a set of typed questions. Answer ALL questions about the ticket and
return ONLY a single JSON object, no prose, no markdown fences.

Question types:
- "noul": answer with a probability between 0 and 1 that the answer is yes.
- "choice": answer with exactly one of the listed option keys.
- "score": answer with exactly one of the listed level keys (the part before
  the colon in each criterion).

Output shape: {"<question_id>": <answer>, ...} with one key per question,
using the same question ids you were given.
"""


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
            endpoint=endpoint, credential=AzureKeyCredential(api_key)
        )

    def run(self, ticket_id: str, state: str, questions: dict[str, Any]) -> RunResult:
        user_prompt = (
            f"Ticket:\n{state}\n\nQuestions (JSON):\n{json.dumps(questions, indent=2)}"
        )
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
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
            input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            output_tokens = getattr(usage, "completion_tokens", None) if usage else None
            raw_usage = _usage_to_dict(usage)
            cached_input_tokens = extract_cached_tokens(raw_usage)
            raw = response.choices[0].message.content
            try:
                answers = json.loads(raw)
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
