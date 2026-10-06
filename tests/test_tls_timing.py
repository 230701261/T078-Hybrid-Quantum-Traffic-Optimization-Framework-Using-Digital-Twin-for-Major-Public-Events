from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import traci

from python.integration.constraint_engine import ConstraintEngine


class TLSTimingConstraintTests(TestCase):
    def validate(self, min_duration, max_duration, requested):
        logic = SimpleNamespace(programID="program-a", phases=[SimpleNamespace(
            duration=10.0, minDur=min_duration, maxDur=max_duration)])
        command = {"action_type": "signal_timing", "sumo_target_id": "tls-a",
                   "parameters": {"phase": 0, "duration_s": requested}}
        with patch.object(traci.trafficlight, "getIDList", return_value=["tls-a"]), \
             patch.object(traci.trafficlight, "getProgram", return_value="program-a"), \
             patch.object(traci.trafficlight, "getCompleteRedYellowGreenDefinition", return_value=[logic]):
            return ConstraintEngine.validate_batch([command])

    def test_supported_range_is_accepted(self):
        result = self.validate(5.0, 30.0, 20.0)
        self.assertTrue(result["valid"])

    def test_fixed_min_max_is_rejected(self):
        result = self.validate(10.0, 10.0, 15.0)
        self.assertFalse(result["valid"])
        self.assertIn("UNSUPPORTED_TLS_TIMING", {error["code"] for error in result["errors"]})

