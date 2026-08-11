"""Minimal Anthropic Messages API adapter using the same ANA Envelope input."""

from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ana.schema import ANAEnvelope, ProviderResult
from .prompt import render_ana_prompt


class AnthropicProviderError(RuntimeError):
    """Raised when the Anthropic Messages API cannot return a valid result."""


PostJSON = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


def _post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise AnthropicProviderError(f"Anthropic API returned HTTP {error.code}: {detail}") from error
    except (URLError, TimeoutError) as error:
        raise AnthropicProviderError("Anthropic API request failed") from error
    except json.JSONDecodeError as error:
        raise AnthropicProviderError("Anthropic API returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise AnthropicProviderError("Anthropic API returned a non-object response")
    return payload


class AnthropicMessagesProvider:
    """Expose a selected Anthropic model as the same ANA text/code Provider."""

    capabilities = frozenset({"text_generation", "code_generation"})

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        *,
        max_tokens: int = 256,
        timeout: float = 30.0,
        post_json: PostJSON = _post_json,
    ) -> None:
        if not model:
            raise ValueError("an explicit Anthropic model ID is required")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._post_json = post_json
        self.provider_id = f"anthropic.messages:{model}"

    def run(self, envelope: ANAEnvelope) -> ProviderResult:
        unsupported = set(envelope.capabilities) - self.capabilities
        if unsupported:
            raise AnthropicProviderError(f"adapter does not support {sorted(unsupported)}")
        if not self.api_key:
            raise AnthropicProviderError("ANTHROPIC_API_KEY is required to call the Anthropic provider")
        response = self._post_json(
            "https://api.anthropic.com/v1/messages",
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": render_ana_prompt(envelope)}],
            },
            self.timeout,
        )
        return ProviderResult(
            provider_id=self.provider_id,
            output={"text": self._extract_text(response), "message_id": response.get("id")},
        )

    @staticmethod
    def _extract_text(response: dict[str, Any]) -> str:
        texts = [
            item.get("text")
            for item in response.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
        ]
        if texts:
            return "".join(texts)
        raise AnthropicProviderError("Anthropic response did not contain text content")
