from __future__ import annotations

import os
import time
from typing import Any

from typesafe_sdk import TypeSafeClient

from .base import Provider, RunResult, extract_cached_tokens


class JevProvider(Provider):
    """Calls typesafe.ai's System One API (Jev) via the official SDK."""

    def __init__(self, name: str, model_id: str, api_key_env: str):
        self.name = name
        self.model_id = model_id
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing env var {api_key_env} for provider {name}")
        self._client = TypeSafeClient(api_key=api_key)

    def run(self, ticket_id: str, state: str, questions: dict[str, Any]) -> RunResult:
        start = time.perf_counter()
        try:
            response = self._client.system_one(
                state=state,
                model=self.model_id,
                questions=questions,
            )
            latency = time.perf_counter() - start
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", None) if usage else None
            output_tokens = getattr(usage, "output_tokens", None) if usage else None
            raw_usage = _usage_to_dict(usage)
            cached_input_tokens = extract_cached_tokens(raw_usage)
            answers = _extract_answers(response)
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
    if usage is None:
        return None
    for method_name in ("as_dict", "to_dict", "model_dump"):
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


def _extract_answers(response: Any) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for attr, field in (("nouls", "noul"), ("choices", "choice"), ("scores", "score")):
        bucket = getattr(response, attr, None)
        if not bucket:
            continue
        for question_id, answer in bucket.items():
            answers[question_id] = getattr(answer, field, answer)
    return answers
