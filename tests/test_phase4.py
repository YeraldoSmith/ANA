import json
from pathlib import Path
import unittest

from benchmarks.phase4_analysis import decompose_case, parameterized_curves


class PhaseFourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1] / "benchmarks" / "phase3_cases.json"
        cls.cases = json.loads(path.read_text(encoding="utf-8"))

    def test_all_existing_cases_have_complete_nonnegative_decomposition(self):
        self.assertEqual(len(self.cases), 12)
        for case in self.cases:
            result = decompose_case(case)
            self.assertGreater(result["baseline"]["total_bytes"], 0)
            self.assertGreater(result["ana"]["total_bytes"], 0)
            self.assertGreaterEqual(result["baseline"]["metadata_bytes"], 0)
            self.assertGreaterEqual(result["ana"]["metadata_bytes"], 0)

    def test_parameterized_curves_cover_required_scales_and_dimensions(self):
        curves = parameterized_curves()
        self.assertEqual(len(curves), 5)
        self.assertEqual(
            {curve["dimension"] for curve in curves},
            {"conversation_history", "project_state", "user_preferences", "repeated_context", "continuation_turns"},
        )
        for curve in curves:
            self.assertEqual([point["scale"] for point in curve["points"]], [1, 5, 10, 25, 50, 100])
            self.assertTrue(all(point["baseline_bytes"] > 0 and point["ana_bytes"] > 0 for point in curve["points"]))
            self.assertTrue(
                all(
                    point["baseline_required_fact_retention"] == point["ana_required_fact_retention"]
                    and point["baseline_required_fact_retention"].split("/")[0]
                    == point["baseline_required_fact_retention"].split("/")[1]
                    for point in curve["points"]
                )
            )


if __name__ == "__main__":
    unittest.main()
