"""A minimal, provider-boundary-preserving OpenAI Responses API adapter."""

from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ana.schema import ANAEnvelope, ProviderResult
from .prompt import render_ana_prompt


class OpenAIProviderError(RuntimeError):
    """Raised when the OpenAI Responses API cannot return a valid result."""


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
        raise OpenAIProviderError(f"OpenAI API returned HTTP {error.code}: {detail}") from error
    except (URLError, TimeoutError) as error:
        raise OpenAIProviderError("OpenAI API request failed") from error
    except json.JSONDecodeError as error:
        raise OpenAIProviderError("OpenAI API returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise OpenAIProviderError("OpenAI API returned a non-object response")
    return payload


class OpenAIResponsesProvider:
    """Expose a selected OpenAI model as an ANA text/code capability Provider.

    The adapter sends only the Envelope input and already selected context.  It
    does not execute tools, persist model-side conversation state, or create
    ProposedActions from unstructured model text.
    """

    capabilities = frozenset({"text_generation", "code_generation"})

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        *,
        timeout: float = 30.0,
        post_json: PostJSON = _post_json,
    ) -> None:
        if not model:
            raise ValueError("an explicit OpenAI model ID is required")
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.timeout = timeout
        self._post_json = post_json
        self.provider_id = f"openai.responses:{model}"

    def run(self, envelope: ANAEnvelope) -> ProviderResult:
        unsupported = set(envelope.capabilities) - self.capabilities
        if unsupported:
            raise OpenAIProviderError(f"adapter does not support {sorted(unsupported)}")
        if not self.api_key:
            raise OpenAIProviderError("OPENAI_API_KEY is required to call the OpenAI provider")
        response = self._post_json(
            "https://api.openai.com/v1/responses",
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            {
                "model": self.model,
                "input": render_ana_prompt(envelope),
                # ANA keeps its own task and Memory state locally.
                "store": False,
            },
            self.timeout,
        )
        text = self._extract_text(response)
        return ProviderResult(
            provider_id=self.provider_id,
            output={"text": text, "response_id": response.get("id")},
        )

    @staticmethod
    def _extract_text(response: dict[str, Any]) -> str:
        direct = response.get("output_text")
        if isinstance(direct, str) and direct:
            return direct
        parts: list[str] = []
        for item in response.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text":
                    text = content.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        if parts:
            return "".join(parts)
        raise OpenAIProviderError("OpenAI response did not contain output text")
