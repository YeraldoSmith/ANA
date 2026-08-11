import json
from pathlib import Path
import unittest

from conformance import node_a, node_b


VECTOR_PATH = Path(__file__).parents[1] / "docs" / "test-vectors" / "ana-v0.1-minimal.json"


class PhaseOneInteropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vector = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))

    def test_node_a_task_to_node_b_and_state_delta_back(self):
        task_wire = node_a.build_envelope_wire(
            self.vector["envelope"], self.vector["envelope_frame"]
        )
        task_frame = json.loads(task_wire.decode("utf-8"))
        self.assertEqual(task_frame["payload"], self.vector["expected_envelope_payload"])

        received_envelope, received_frame = node_b.receive_envelope(task_wire)
        self.assertEqual(received_envelope, self.vector["envelope"])
        self.assertEqual(received_frame["message_id"], self.vector["envelope_frame"]["message_id"])

        state_wire = node_b.build_routed_state_delta(
            received_envelope, received_frame, self.vector["state_delta_frame"]
        )
        state_frame = json.loads(state_wire.decode("utf-8"))
        self.assertEqual(state_frame["payload"], self.vector["expected_state_delta_payload"])

        delta = node_a.receive_state_delta(
            state_wire,
            expected_stream_id=self.vector["envelope"]["task_id"],
            previous_message_id=self.vector["envelope_frame"]["message_id"],
            previous_sequence=self.vector["envelope_frame"]["sequence"],
        )
        self.assertEqual(delta, self.vector["expected_state_delta"])

    def test_node_b_rejects_unknown_chain_before_parsing_payload(self):
        task_wire = node_a.build_envelope_wire(
            self.vector["envelope"], self.vector["envelope_frame"]
        )
        frame = json.loads(task_wire.decode("utf-8"))
        frame["chain_version"] = "9.9"
        with self.assertRaises(node_b.NodeBProtocolError):
            node_b.receive_envelope(node_b.canonical(frame).encode("utf-8"))

    def test_node_a_rejects_state_delta_with_broken_causality(self):
        task_wire = node_a.build_envelope_wire(
            self.vector["envelope"], self.vector["envelope_frame"]
        )
        envelope, task_frame = node_b.receive_envelope(task_wire)
        state_wire = node_b.build_routed_state_delta(
            envelope, task_frame, self.vector["state_delta_frame"]
        )
        frame = json.loads(state_wire.decode("utf-8"))
        delta = json.loads(frame["payload"])
        delta["parent_event_id"] = "wrong-parent"
        frame["payload"] = node_b.canonical(delta)
        with self.assertRaises(node_a.NodeAProtocolError):
            node_a.receive_state_delta(
                node_b.canonical(frame).encode("utf-8"),
                expected_stream_id=self.vector["envelope"]["task_id"],
                previous_message_id=self.vector["envelope_frame"]["message_id"],
                previous_sequence=0,
            )


if __name__ == "__main__":
    unittest.main()
