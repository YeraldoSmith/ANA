"""Run a complete local-runtime -> adapter -> policy -> executor flow."""

from pathlib import Path
from tempfile import TemporaryDirectory

from adapters.mock import MockCodeProvider
from ana.executor import ActionExecutor
from ana.memory import MemoryStore
from ana.policy import LocalPolicy
from ana.router import CapabilityRouter
from ana.schema import ANAEnvelope, MemoryRecord


def main() -> None:
    memory = MemoryStore()
    preference = MemoryRecord(kind="preference", content={"security_priority": "high"})
    memory.add(preference)
    envelope = ANAEnvelope(
        intent="generate",
        capabilities=("code_generation",),
        input={"text": "Generate a Java hello-world program"},
        context={"language": "java"},
        memory_refs=(preference.id,),
        policy={"execution_mode": "sandbox_first"},
    )
    result = CapabilityRouter([MockCodeProvider()]).select(envelope).run(envelope)
    with TemporaryDirectory(prefix="ana-demo-") as temporary_directory:
        executor = ActionExecutor(LocalPolicy(Path(temporary_directory)))
        created = [executor.execute(action) for action in result.proposed_actions]
        print(result.output["text"])
        print(f"Provider: {result.provider_id}")
        print(f"Created: {created[0]}")


if __name__ == "__main__":
    main()
