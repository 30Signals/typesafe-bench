from __future__ import annotations

import json
import os
import time
from typing import Any

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

from .base import Provider, RunResult

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
    """Generic adapter for any model deployed on Azure AI Foundry, reached via
    the unified azure-ai-inference ChatCompletionsClient. Works the same way
    regardless of whether the underlying deployment is a GPT or Claude model."""

    def __init__(
        self,
        name: str,
        endpoint_env: str,
        api_key_env: str,
        deployment_env: str | None = None,
    ):
        self.name = name
        endpoint = os.environ.get(endpoint_env)
        api_key = os.environ.get(api_key_env)
        if not endpoint or not api_key:
            raise RuntimeError(
                f"Missing {endpoint_env} and/or {api_key_env} for provider {name}"
            )
        self.deployment = os.environ.get(deployment_env) if deployment_env else None
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
        kwargs: dict[str, Any] = {"messages": messages, "response_format": "json_object"}
        if self.deployment:
            kwargs["model"] = self.deployment

        start = time.perf_counter()
        try:
            response = self._client.complete(**kwargs)
            latency = time.perf_counter() - start
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            output_tokens = getattr(usage, "completion_tokens", None) if usage else None
            raw = response.choices[0].message.content
            try:
                answers = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                answers = None
                return RunResult(
                    model_name=self.name,
                    ticket_id=ticket_id,
                    latency_s=latency,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    answers=None,
                    error=f"non-JSON response: {raw!r}",
                )
            return RunResult(
                model_name=self.name,
                ticket_id=ticket_id,
                latency_s=latency,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
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
