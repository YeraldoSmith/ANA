import json
from pathlib import Path
import unittest

from benchmarks.phase5_analysis import ablate_envelope, fidelity_results, packets_for_turn


class PhaseFiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1] / "benchmarks" / "phase5_parameters.json"
        cls.config = json.loads(path.read_text(encoding="utf-8"))

    def test_smart_and_ana_have_identical_selected_context(self):
        _naive, smart, ana, facts = packets_for_turn(self.config, 10)
        self.assertEqual(smart["context"], ana["context"])
        smart_wire = json.dumps(smart, sort_keys=True)
        ana_wire = json.dumps(ana, sort_keys=True)
        self.assertTrue(all(fact in smart_wire and fact in ana_wire for fact in facts))

    def test_envelope_ablation_has_positive_existing_field_costs(self):
        _naive, _smart, ana, _facts = packets_for_turn(self.config, 1)
        result = ablate_envelope(ana)
        self.assertGreater(result["full_envelope_bytes"], 0)
        for name, value in result.items():
            if name != "full_envelope_bytes":
                self.assertGreater(value, 0, name)

    def test_memory_fidelity_vectors_retain_current_facts_and_exclude_stale_ones(self):
        results = fidelity_results()
        self.assertEqual(len(results), 5)
        self.assertTrue(all(result["selection_fidelity"] for result in results))


if __name__ == "__main__":
    unittest.main()
