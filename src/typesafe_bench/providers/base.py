from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RunResult:
    model_name: str
    ticket_id: str
    latency_s: float
    input_tokens: int | None
    output_tokens: int | None
    answers: dict[str, Any] | None
    error: str | None = None


class Provider:
    """Common interface: run one ticket's set of questions in a single call."""

    name: str

    def run(self, ticket_id: str, state: str, questions: dict[str, Any]) -> RunResult:
        raise NotImplementedError
