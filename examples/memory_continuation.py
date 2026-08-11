"""Demonstrate that Memory continuation is independent of the selected model."""

from adapters.continuation_demo import ContinuationProbeProvider
from ana.continuation import build_continuation_envelope, continue_with_provider
from ana.memory import MemoryStore
from ana.schema import MemoryRecord


def main() -> None:
    memory = MemoryStore()
    preference = MemoryRecord(kind="preference", content={"language": "java"})
    semantic = MemoryRecord(kind="semantic", content={"priority": "security_first"})
    memory.add(preference)
    memory.add(semantic)
    envelope = build_continuation_envelope(
        memory,
        request="Continue the implementation using the remembered constraints.",
        memory_refs=(preference.id, semantic.id),
    )

    for provider_id in ("ana.demo-model-a", "ana.demo-model-b"):
        result = continue_with_provider(ContinuationProbeProvider(provider_id), envelope)
        print(f"{result.provider_id}: {result.output['memory_seen']}")


if __name__ == "__main__":
    main()
