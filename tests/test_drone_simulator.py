"""Simulator command de-duplication without a broker."""
import json
import time
import unittest
from unittest.mock import patch

from simulation import drone_sim


class DroneSimulatorTests(unittest.TestCase):
    def setUp(self):
        if drone_sim.worker_thread and drone_sim.worker_thread.is_alive():
            drone_sim.stop_event.set()
            drone_sim.worker_thread.join(timeout=1)
        drone_sim.mission_active.clear()
        drone_sim.stop_event.clear()
        drone_sim.state.update(x=0.0, y=0.0, altitude=0.0, battery=100.0, status="idle", mission_id=None, mission_status=None)

    def test_duplicate_mission_starts_one_worker(self):
        message = type("Message", (), {"topic": "drone/mission", "payload": json.dumps({
            "mission_id": "duplicate-safe", "drone_id": drone_sim.DRONE_ID, "token": drone_sim.TOKEN,
            "waypoints": [{"x": 1, "y": 1}],
        }).encode()})()
        with patch.object(drone_sim.threading, "Thread") as thread:
            drone_sim.on_message(None, None, message)
            drone_sim.on_message(None, None, message)
        thread.assert_called_once()
        self.assertTrue(drone_sim.mission_active.is_set())

    def test_validation_rejects_wrong_identity_and_empty_waypoints(self):
        for payload in (
            {"mission_id": "bad-token", "drone_id": drone_sim.DRONE_ID, "token": "bad", "waypoints": [{"x": 1, "y": 1}]},
            {"mission_id": "wrong-drone", "drone_id": "other", "token": drone_sim.TOKEN, "waypoints": [{"x": 1, "y": 1}]},
            {"mission_id": "empty", "drone_id": drone_sim.DRONE_ID, "token": drone_sim.TOKEN, "waypoints": []},
        ):
            self.assertIsNone(drone_sim._validate_mission(json.dumps(payload).encode()))

    def test_worker_moves_inspects_and_returns_home(self):
        original_step = drone_sim.STEP_SECONDS
        drone_sim.STEP_SECONDS = 0.01
        try:
            drone_sim._fly("flight", [{"x": 2.0, "y": 1.0, "altitude": 2.0, "dwell_seconds": 0.01}])
        finally:
            drone_sim.STEP_SECONDS = original_step
        with drone_sim.state_lock:
            self.assertEqual((drone_sim.state["x"], drone_sim.state["y"], drone_sim.state["altitude"]), (0.0, 0.0, 0.0))
            self.assertEqual(drone_sim.state["status"], "idle")
            self.assertEqual(drone_sim.state["mission_status"], "completed")
            self.assertLess(drone_sim.state["battery"], 100.0)


if __name__ == "__main__":
    unittest.main()
