from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel

from .llm import LlmUsage, StructuredLlmResult


class OpenAiStructuredClient:
    """OpenAI Responses API adapter with native Pydantic structured output."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = model
        if client is not None:
            self._client = client
            return
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI support is not installed; install chemresearch-agent[llm-openai]"
            ) from exc
        options = {"api_key": api_key}
        if base_url:
            options["base_url"] = base_url
        self._client = OpenAI(**options)

    def generate[ResponseT: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseT],
        operation: str,
    ) -> StructuredLlmResult[ResponseT]:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text_format=response_model,
        )
        value = response.output_parsed
        if value is None:
            raise RuntimeError(f"{operation} returned no parsed structured output")
        usage = getattr(response, "usage", None)
        return StructuredLlmResult(
            value=value,
            model=self._model,
            usage=LlmUsage(
                input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
                output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            ),
            request_id=getattr(response, "id", None),
        )


def openai_client_from_env() -> OpenAiStructuredClient | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAiStructuredClient(
        model=os.getenv("OPENAI_MODEL", "gpt-5.6"),
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
