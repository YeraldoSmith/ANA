import json
from pathlib import Path
import unittest

from adapters.continuation_demo import ContinuationProbeProvider
from adapters.openai_responses import OpenAIResponsesProvider
from ana.continuation import build_continuation_envelope, continue_with_provider
from ana.memory import MemoryStore
from ana.schema import MemoryRecord
from benchmarks.run_continuation_benchmark import run_case


class PhaseTwoTests(unittest.TestCase):
    def test_openai_adapter_uses_responses_contract_without_actions(self):
        captured = {}

        def fake_post(url, headers, body, timeout):
            captured.update(url=url, headers=headers, body=body, timeout=timeout)
            return {"id": "resp_123", "output": [{"content": [{"type": "output_text", "text": "ok"}]}]}

        provider = OpenAIResponsesProvider("test-model", api_key="test-key", post_json=fake_post)
        envelope = build_continuation_envelope(
            MemoryStore(), request="Say ok", memory_refs=(), task_id="adapter-test"
        )
        result = provider.run(envelope)
        self.assertEqual(captured["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["body"]["model"], "test-model")
        self.assertFalse(captured["body"]["store"])
        self.assertEqual(result.output["text"], "ok")
        self.assertEqual(result.proposed_actions, ())

    def test_same_memory_continues_through_replaceable_providers(self):
        memory = MemoryStore()
        preference = MemoryRecord(kind="preference", content={"language": "java"})
        semantic = MemoryRecord(kind="semantic", content={"priority": "security_first"})
        memory.add(preference)
        memory.add(semantic)
        envelope = build_continuation_envelope(
            memory, request="Continue", memory_refs=(preference.id, semantic.id)
        )
        first = continue_with_provider(ContinuationProbeProvider("provider-a"), envelope)
        second = continue_with_provider(ContinuationProbeProvider("provider-b"), envelope)
        self.assertEqual(first.output["memory_seen"], second.output["memory_seen"])
        self.assertEqual(first.output["memory_seen"]["preferences"][0]["language"], "java")
        self.assertEqual(second.output["memory_seen"]["semantic"][0]["priority"], "security_first")

    def test_benchmark_preserves_required_facts_with_smaller_ana_payload(self):
        path = Path(__file__).parents[1] / "benchmarks" / "continuation_cases.json"
        case = json.loads(path.read_text(encoding="utf-8"))[0]
        result = run_case(case)
        self.assertTrue(result["baseline_contains_required_facts"])
        self.assertTrue(result["ana_contains_required_facts"])
        self.assertGreater(result["saved_utf8_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
