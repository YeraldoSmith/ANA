"""Phase 7 cross-language ANA v0.1 Core conformance suite."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from conformance import node_a, node_b


ROOT = Path(__file__).parents[1]
VECTORS = ROOT / "docs" / "test-vectors"
JAVA_SOURCE = ROOT / "conformance" / "independent-java" / "AnaV01Node.java"


class PhaseSevenConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("javac") or not shutil.which("java"):
            raise unittest.SkipTest("Phase 7 independent Java conformance requires a JDK")
        cls.build = tempfile.TemporaryDirectory(prefix="ana-phase7-java-")
        compiled = subprocess.run(
            ["javac", "-d", cls.build.name, str(JAVA_SOURCE)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if compiled.returncode:
            raise RuntimeError(f"independent Java node did not compile: {compiled.stderr}")
        cls.vector = json.loads((VECTORS / "ana-v0.1-minimal.json").read_text(encoding="utf-8"))
        cls.negative = json.loads((VECTORS / "ana-v0.1-negative.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def java(self, operation: str, value: object, *, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
        source = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        completed = subprocess.run(
            ["java", "-cp", self.build.name, "AnaV01Node", operation],
            cwd=ROOT,
            input=source,
            text=True,
            capture_output=True,
        )
        if expect_success:
            self.assertEqual(completed.returncode, 0, completed.stderr)
        else:
            self.assertNotEqual(completed.returncode, 0, completed.stdout)
        return completed

    def _python_task_wire(self) -> bytes:
        return node_a.build_envelope_wire(self.vector["envelope"], self.vector["envelope_frame"])

    def _python_state_wire(self) -> bytes:
        task_wire = self._python_task_wire()
        envelope, task_frame = node_b.receive_envelope(task_wire)
        return node_b.build_routed_state_delta(envelope, task_frame, self.vector["state_delta_frame"])

    def test_python_reference_to_independent_java_to_python_reference(self):
        task_wire = self._python_task_wire()
        accepted_payload = self.java("accept-envelope", task_wire.decode("utf-8")).stdout
        self.assertEqual(accepted_payload, self.vector["expected_envelope_payload"])

        task_frame = json.loads(task_wire)
        java_state_wire = self.java(
            "emit-state-delta",
            {
                "envelope": self.vector["envelope"],
                "task_frame": task_frame,
                "state_delta_frame": self.vector["state_delta_frame"],
            },
        ).stdout.encode("utf-8")
        java_state_frame = json.loads(java_state_wire)
        self.assertEqual(java_state_frame["payload"], self.vector["expected_state_delta_payload"])
        self.assertEqual(
            node_a.receive_state_delta(
                java_state_wire,
                expected_stream_id=self.vector["envelope"]["task_id"],
                previous_message_id=self.vector["envelope_frame"]["message_id"],
                previous_sequence=0,
            ),
            self.vector["expected_state_delta"],
        )

    def test_independent_java_to_python_reference_to_independent_java(self):
        java_task_wire = self.java(
            "emit-envelope",
            {"envelope": self.vector["envelope"], "envelope_frame": self.vector["envelope_frame"]},
        ).stdout.encode("utf-8")
        envelope, task_frame = node_b.receive_envelope(java_task_wire)
        self.assertEqual(json.loads(java_task_wire)["payload"], self.vector["expected_envelope_payload"])
        python_state_wire = node_b.build_routed_state_delta(
            envelope, task_frame, self.vector["state_delta_frame"]
        )
        validated_payload = self.java(
            "validate-state-delta",
            {
                "wire": python_state_wire.decode("utf-8"),
                "expected_stream_id": self.vector["envelope"]["task_id"],
                "previous_message_id": self.vector["envelope_frame"]["message_id"],
                "previous_sequence": 0,
            },
        ).stdout
        self.assertEqual(validated_payload, self.vector["expected_state_delta_payload"])

    def test_canonical_and_memory_state_vectors_are_provider_neutral(self):
        canonical_cases = json.loads((VECTORS / "ana-v0.1-canonical.json").read_text(encoding="utf-8"))["cases"]
        for case in canonical_cases:
            with self.subTest(case=case["id"]):
                raw = json.dumps(case["input"], ensure_ascii=False)
                self.assertEqual(node_b.canonical(case["input"]), case["expected_canonical"])
                self.assertEqual(self.java("canonicalize", raw).stdout, case["expected_canonical"])

        bundle = json.loads((VECTORS / "ana-v0.1-memory-state.json").read_text(encoding="utf-8"))
        imported = self.java("import-state-bundle", bundle).stdout
        self.assertEqual(json.loads(imported), bundle)
        self.assertIn('"execution_mode":"sandbox_first"', imported)
        self.assertNotIn("openai", imported.lower())
        self.assertNotIn("anthropic", imported.lower())

    def test_fixed_negative_vectors_have_matching_rejection_behavior(self):
        for case in self.negative["cases"]:
            with self.subTest(case=case["id"]):
                target = case["target"]
                if target == "frame":
                    frame = json.loads(self._python_task_wire())
                    frame.update(case["patch"])
                    wire = node_b.canonical(frame).encode("utf-8")
                    java_result = self.java("accept-envelope", wire.decode("utf-8"), expect_success=False)
                    with self.assertRaises(node_b.NodeBProtocolError):
                        node_b.receive_envelope(wire)
                elif target == "envelope":
                    envelope = deepcopy(self.vector["envelope"])
                    envelope.update(case["patch"])
                    frame = json.loads(self._python_task_wire())
                    frame["payload"] = node_b.canonical(envelope)
                    wire = node_b.canonical(frame).encode("utf-8")
                    java_result = self.java("accept-envelope", wire.decode("utf-8"), expect_success=False)
                    with self.assertRaises(node_b.NodeBProtocolError):
                        node_b.receive_envelope(wire)
                elif target == "state_frame":
                    frame = json.loads(self._python_state_wire())
                    frame.update(case["patch"])
                    wire = node_b.canonical(frame).encode("utf-8")
                    java_result = self.java(
                        "validate-state-delta",
                        {
                            "wire": wire.decode("utf-8"),
                            "expected_stream_id": self.vector["envelope"]["task_id"],
                            "previous_message_id": self.vector["envelope_frame"]["message_id"],
                            "previous_sequence": 0,
                        },
                        expect_success=False,
                    )
                    with self.assertRaises(node_a.NodeAProtocolError):
                        node_a.receive_state_delta(
                            wire,
                            expected_stream_id=self.vector["envelope"]["task_id"],
                            previous_message_id=self.vector["envelope_frame"]["message_id"],
                            previous_sequence=0,
                        )
                else:
                    frame = json.loads(self._python_state_wire())
                    delta = json.loads(frame["payload"])
                    delta.update(case["patch"])
                    frame["payload"] = node_b.canonical(delta)
                    wire = node_b.canonical(frame).encode("utf-8")
                    java_result = self.java(
                        "validate-state-delta",
                        {
                            "wire": wire.decode("utf-8"),
                            "expected_stream_id": self.vector["envelope"]["task_id"],
                            "previous_message_id": self.vector["envelope_frame"]["message_id"],
                            "previous_sequence": 0,
                        },
                        expect_success=False,
                    )
                    with self.assertRaises(node_a.NodeAProtocolError):
                        node_a.receive_state_delta(
                            wire,
                            expected_stream_id=self.vector["envelope"]["task_id"],
                            previous_message_id=self.vector["envelope_frame"]["message_id"],
                            previous_sequence=0,
                        )
                self.assertIn(f"ERROR:{case['expected_java_error']}:", java_result.stderr)


if __name__ == "__main__":
    unittest.main()
