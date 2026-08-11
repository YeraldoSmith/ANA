import json
from pathlib import Path
import unittest

from adapters.anthropic_messages import AnthropicMessagesProvider
from adapters.openai_responses import OpenAIResponsesProvider
from ana.continuation import build_continuation_envelope
from ana.memory import MemoryStore
from ana.schema import MemoryRecord
from benchmarks.run_phase3_benchmark import run_case


class PhaseThreeTests(unittest.TestCase):
    def test_openai_and_anthropic_receive_the_same_ana_memory_prompt(self):
        captured = {}

        def openai_post(_url, _headers, body, _timeout):
            captured["openai"] = body
            return {"id": "resp_1", "output_text": "continued"}

        def anthropic_post(_url, headers, body, _timeout):
            captured["anthropic"] = body
            captured["anthropic_headers"] = headers
            return {"id": "msg_1", "content": [{"type": "text", "text": "continued"}]}

        memory = MemoryStore()
        preference = MemoryRecord(kind="preference", content={"language": "java"})
        semantic = MemoryRecord(kind="semantic", content={"priority": "security_first"})
        memory.add(preference)
        memory.add(semantic)
        envelope = build_continuation_envelope(
            memory, request="Continue", memory_refs=(preference.id, semantic.id)
        )

        openai = OpenAIResponsesProvider("openai-test", api_key="test", post_json=openai_post)
        anthropic = AnthropicMessagesProvider("anthropic-test", api_key="test", post_json=anthropic_post)
        openai_result = openai.run(envelope)
        anthropic_result = anthropic.run(envelope)
        self.assertEqual(openai_result.output["text"], "continued")
        self.assertEqual(anthropic_result.output["text"], "continued")
        self.assertEqual(openai_result.proposed_actions, ())
        self.assertEqual(anthropic_result.proposed_actions, ())
        self.assertEqual(captured["openai"]["input"], captured["anthropic"]["messages"][0]["content"])
        self.assertEqual(captured["anthropic_headers"]["anthropic-version"], "2023-06-01")

    def test_phase3_vectors_are_fair_about_required_facts(self):
        path = Path(__file__).parents[1] / "benchmarks" / "phase3_cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 12)
        categories = {case["category"] for case in cases}
        self.assertEqual(
            categories,
            {
                "simple_task",
                "code_generation_modification",
                "long_context_continuation",
                "user_preference",
                "project_state",
                "state_delta",
            },
        )
        for case in cases:
            result = run_case(case)
            expected = f"{len(case['required_facts'])}/{len(case['required_facts'])}"
            self.assertEqual(result["baseline_required_fact_retention"], expected, case["case_id"])
            self.assertEqual(result["ana_required_fact_retention"], expected, case["case_id"])


if __name__ == "__main__":
    unittest.main()
