"""Regression tests for incident/mission idempotence policy."""
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Incident, Mission
from backend.services.action_dispatcher import ActionDispatcher


class FakeMission:
    def __init__(self, mission_id="mission-1"):
        self.mission_id = mission_id


class FakeManager:
    mission = None

    def __init__(self):
        self.calls = 0

    def create_inspection(self, *_args, **_kwargs):
        self.calls += 1
        self.mission = type("Active", (), {"mission_id": "mission-1", "status": type("Status", (), {"value": "created"})()})()
        return FakeMission()


class ActionDispatcherTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.manager = FakeManager()
        self.dispatcher = ActionDispatcher(self.db, self.manager)

    def tearDown(self):
        self.db.close()

    def test_repeated_anomaly_updates_one_incident_and_one_mission(self):
        first = self.dispatcher.handle_detection("portique_P01", "ml_anomaly", "high", "vibration anomaly", True)
        second = self.dispatcher.handle_detection("portique_P01", "ml_anomaly", "high", "vibration anomaly", True)
        incident = self.db.query(Incident).one()
        self.assertTrue(first["incident_created"])
        self.assertFalse(second["incident_created"])
        self.assertEqual(incident.occurrence_count, 2)
        self.assertEqual(self.manager.calls, 1)

    def test_active_database_mission_rejects_second_dispatch(self):
        self.db.add(Mission(mission_id="active-1", device_id="camera_Q01", drone_id="drone_01", status="active", created_at=datetime.utcnow()))
        self.db.commit()
        result = self.dispatcher.handle_detection("portique_P01", "ml_anomaly", "high", "anomaly", True)
        self.assertEqual(result["dispatch_reason"], "active_mission:active-1")
        self.assertEqual(self.manager.calls, 0)

    def test_cooldown_blocks_a_completed_mission_for_same_device(self):
        self.db.add(Mission(mission_id="completed-1", device_id="portique_P01", drone_id="drone_01", status="completed", created_at=datetime.utcnow()))
        self.db.commit()
        allowed, reason = self.dispatcher.should_dispatch_drone("portique_P01", "ml_anomaly", "critical")
        self.assertFalse(allowed)
        self.assertEqual(reason, "cooldown")


if __name__ == "__main__":
    unittest.main()
