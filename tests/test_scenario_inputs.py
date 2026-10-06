import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.scenario_inputs import default_density, validate_density


class ScenarioInputTests(unittest.TestCase):
    def test_defaults_are_derived_from_existing_route_flows(self):
        normal = default_density("normal_day")
        event = default_density("event_day")
        self.assertEqual(set(normal), {"cars", "buses", "two_wheelers", "pedestrians", "local_trains"})
        self.assertGreater(event["cars"], normal["cars"])
        self.assertGreater(event["pedestrians"], normal["pedestrians"])

    def test_density_validation_rejects_invalid_values_and_fields(self):
        with self.assertRaises(ValueError):
            validate_density({"cars": -1}, "normal_day")
        with self.assertRaises(ValueError):
            validate_density({"cars": 1.5}, "normal_day")
        with self.assertRaises(ValueError):
            validate_density({"unknown_mode": 1}, "normal_day")

    def test_valid_density_preserves_all_configured_modes(self):
        actual = {"cars": 100, "buses": 4, "two_wheelers": 80, "pedestrians": 200, "local_trains": 2}
        self.assertEqual(validate_density(actual, "normal_day"), actual)


if __name__ == "__main__":
    unittest.main()
