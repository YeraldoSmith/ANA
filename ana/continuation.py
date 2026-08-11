"""Minimal model-neutral Memory continuation helper for Phase 2."""

from __future__ import annotations

from .memory import MemoryStore
from .router import CapabilityRouter, Provider
from .schema import ANAEnvelope, ProviderResult


def build_continuation_envelope(
    memory: MemoryStore,
    *,
    request: str,
    memory_refs: tuple[str, ...],
    task_id: str = "continuation-demo",
) -> ANAEnvelope:
    """Select explicit local records and form a provider-neutral continuation."""
    selected = []
    for record_id in memory_refs:
        record = memory.get(record_id)
        if record.portability == "ephemeral":
            continue
        selected.append({"id": record.id, "kind": record.kind, "content": record.content})
    return ANAEnvelope(
        intent="continue",
        capabilities=("text_generation",),
        input={"text": request},
        context={"memory": selected},
        memory_refs=memory_refs,
        task_id=task_id,
    )


def continue_with_provider(
    provider: Provider, envelope: ANAEnvelope) -> ProviderResult:
    """Run the same continuation envelope through any compatible Provider."""
    return CapabilityRouter([provider]).select(envelope).run(envelope)
