"""Deterministic provider used to demonstrate model-independent continuation."""

from __future__ import annotations

from ana.schema import ANAEnvelope, ProviderResult


class ContinuationProbeProvider:
    """A test provider that reports the selected local Memory it received."""

    capabilities = frozenset({"text_generation"})

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id

    def run(self, envelope: ANAEnvelope) -> ProviderResult:
        memory = envelope.context.get("memory", [])
        preferences = [item["content"] for item in memory if item.get("kind") == "preference"]
        semantic = [item["content"] for item in memory if item.get("kind") == "semantic"]
        return ProviderResult(
            provider_id=self.provider_id,
            output={
                "text": "Continuation context accepted.",
                "memory_seen": {"preferences": preferences, "semantic": semantic},
            },
        )
