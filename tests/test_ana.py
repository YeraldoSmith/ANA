import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from adapters.mock import MockCodeProvider
from ana.chain import ANAChain
from ana.executor import ActionExecutor
from ana.memory import MemoryStore
from ana.policy import Decision, LocalPolicy
from ana.router import CapabilityRouter
from ana.schema import ANAEnvelope, MemoryRecord, ProposedAction


class ANATests(unittest.TestCase):
    def test_chain_round_trip_with_unicode(self):
        original = "Hello, ANA — 本地与云端"
        stream = ANAChain.encode(original, ("xor_a5", "reverse", "rotate_left"))
        self.assertEqual(ANAChain.decode(stream), original)

    def test_portable_export_excludes_device_local_state(self):
        memory = MemoryStore()
        portable = MemoryRecord(kind="preference", content={"style": "detailed"})
        local = MemoryRecord(kind="cache", content={"path": "/tmp"}, portability="device_local")
        memory.add(portable)
        memory.add(local)
        profile = memory.export_profile()
        self.assertEqual(profile.records, (portable,))

    def test_router_and_mock_provider(self):
        envelope = ANAEnvelope(
            intent="generate",
            capabilities=("code_generation",),
            input={"text": "hello"},
            context={"language": "java"},
        )
        provider = CapabilityRouter([MockCodeProvider()]).select(envelope)
        self.assertEqual(provider.run(envelope).proposed_actions[0].target, "generated/Hello.java")

    def test_policy_denies_workspace_escape(self):
        with TemporaryDirectory() as directory:
            policy = LocalPolicy(Path(directory))
            action = ProposedAction(kind="write_file", target="../outside.txt", content="no")
            self.assertEqual(policy.decide(action), Decision.DENY)

    def test_executor_writes_only_after_allow(self):
        with TemporaryDirectory() as directory:
            workspace = Path(directory)
            created = ActionExecutor(LocalPolicy(workspace)).execute(
                ProposedAction(kind="write_file", target="out/ok.txt", content="ANA")
            )
            self.assertEqual(created.read_text(encoding="utf-8"), "ANA")


if __name__ == "__main__":
    unittest.main()
