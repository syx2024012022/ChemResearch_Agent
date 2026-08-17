from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class LlmUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class StructuredLlmResult[ResponseT: BaseModel](BaseModel):
    value: ResponseT
    model: str
    usage: LlmUsage
    request_id: str | None = None


class StructuredLlmClient(Protocol):
    """Provider-neutral structured generation contract."""

    def generate[ResponseT: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseT],
        operation: str,
    ) -> StructuredLlmResult[ResponseT]: ...
