import unittest

from adapters.anthropic_messages import AnthropicMessagesProvider
from adapters.openai_responses import OpenAIResponsesProvider
from examples.cross_provider_continuity import (
    build_fixed_local_context,
    build_handoff_envelope,
    run_failure_cases,
    run_offline_demo,
)


class PhaseSixTests(unittest.TestCase):
    def test_both_provider_handoff_directions_preserve_local_state(self):
        result = run_offline_demo()
        self.assertEqual(len(result["migrations"]), 2)
        self.assertEqual(
            {item["migration"] for item in result["migrations"]},
            {"openai-contract -> anthropic-contract", "anthropic-contract -> openai-contract"},
        )
        for migration in result["migrations"]:
            self.assertTrue(all(migration["continuity_assertions"].values()), migration["migration"])
            self.assertEqual(migration["state_diff"]["phase"], ["scaffolded", "implementation"])
            self.assertEqual(migration["state_diff"]["sequence"], [4, 5])

    def test_failure_cases_are_detected_without_mutating_local_state(self):
        failures = run_failure_cases()
        self.assertEqual(len(failures), 5)
        for failure in failures:
            self.assertFalse(failure["accepted"], failure["case"])
            self.assertEqual(failure["detected"], failure["expected"], failure["case"])
            self.assertTrue(failure["local_state_unchanged"], failure["case"])

    def test_real_adapter_boundaries_receive_neutral_handoff_without_schema_migration(self):
        captured = {}

        def openai_post(_url, _headers, body, _timeout):
            captured["openai"] = body
            return {"id": "resp_phase6", "output_text": "acknowledged"}

        def anthropic_post(_url, _headers, body, _timeout):
            captured["anthropic"] = body
            return {"id": "msg_phase6", "content": [{"type": "text", "text": "acknowledged"}]}

        memory, selected_ids, state = build_fixed_local_context()
        envelope = build_handoff_envelope(
            memory, selected_ids, state, task_id="phase6-adapter-contract", request="Continue safely."
        )
        openai = OpenAIResponsesProvider("openai-test", api_key="test", post_json=openai_post)
        anthropic = AnthropicMessagesProvider("anthropic-test", api_key="test", post_json=anthropic_post)
        self.assertEqual(openai.run(envelope).proposed_actions, ())
        self.assertEqual(anthropic.run(envelope).proposed_actions, ())
        self.assertEqual(captured["openai"]["input"], captured["anthropic"]["messages"][0]["content"])
        self.assertNotIn("history", envelope.context)
        for record in envelope.context["memory"]:
            self.assertNotIn("openai", str(record).lower())
            self.assertNotIn("anthropic", str(record).lower())


if __name__ == "__main__":
    unittest.main()
