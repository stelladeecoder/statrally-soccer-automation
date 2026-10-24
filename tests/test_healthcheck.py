import unittest
from statrally_automation.healthcheck import run


class HealthCheckTests(unittest.TestCase):
    def test_scaffold_never_claims_live_predictions(self):
        result = run()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["mode"], "scaffold_only")


if __name__ == "__main__":
    unittest.main()
