"""Capability-based routing; vendors are implementation details."""

from __future__ import annotations

from typing import Protocol

from .schema import ANAEnvelope, ProviderResult


class Provider(Protocol):
    provider_id: str
    capabilities: frozenset[str]

    def run(self, envelope: ANAEnvelope) -> ProviderResult: ...


class CapabilityRouter:
    def __init__(self, providers: list[Provider]) -> None:
        self._providers = providers

    def select(self, envelope: ANAEnvelope) -> Provider:
        required = set(envelope.capabilities)
        for provider in self._providers:
            if required.issubset(provider.capabilities):
                return provider
        raise LookupError(f"no provider supports {sorted(required)}")
