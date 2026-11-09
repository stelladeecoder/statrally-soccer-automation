"""Guard against two independent publishers posting the same results to Discord."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GRADING_WORKFLOW = ROOT / ".github" / "workflows" / "m13-beta-grading.yml"


class ResultsPublisherConfigurationTests(unittest.TestCase):
    def test_grading_workflow_has_one_results_publisher(self):
        workflow = GRADING_WORKFLOW.read_text(encoding="utf-8")
        # Canonical publisher owns durable results reservations.
        self.assertEqual(
            workflow.count("run: python automation/src/prediction_platform.py results"),
            1,
        )
        # The legacy beta publisher has separate reservations and would
        # duplicate some results if run against the same webhook.
        self.assertNotIn(
            "run: python automation/src/m13_beta_grade_issues.py",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
