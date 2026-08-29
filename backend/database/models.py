"""Persistence models for operational telemetry, SIEM and mission records."""
import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    type = Column(String)
    value = Column(Float, nullable=True)
    unit = Column(String, nullable=True)
    status = Column(String, nullable=True)
    people_count = Column(Integer, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    timestamp = Column(Float)
    received_at = Column(DateTime, default=datetime.datetime.utcnow)
    ip_src = Column(String, nullable=True)
    mac_src = Column(String, nullable=True)
    port_src = Column(Integer, nullable=True)
    packet_size = Column(Integer, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String)
    alert_type = Column(String)
    message = Column(Text)
    timestamp = Column(Float)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    severity = Column(String, nullable=True)


class NetworkFlow(Base):
    __tablename__ = "network_flows"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    ip_src = Column(String)
    mac_src = Column(String)
    packet_count = Column(Integer)
    bytes_total = Column(Integer)
    start_time = Column(Float)
    end_time = Column(Float)
    avg_interval = Column(Float)
    alert = Column(Boolean, default=False)


class Mission(Base):
    __tablename__ = "missions"
    id = Column(Integer, primary_key=True, index=True)
    mission_id = Column(String, unique=True)
    device_id = Column(String)
    # Physical column name is retained for existing SQLite files; Python/API name is drone_id.
    drone_id = Column("robot_id", String)
    target_x = Column(Float, nullable=True)
    target_y = Column(Float, nullable=True)
    status = Column(String, index=True, default="created")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    anomaly_type = Column(String, index=True)
    severity = Column(String)
    status = Column(String, default="open")
    description = Column(Text)
    drone_mission_id = Column("robot_mission_id", String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    first_seen = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    last_seen = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    occurrence_count = Column(Integer, default=1, nullable=False)
    dedup_key = Column(String, nullable=True, index=True)
    resolved_at = Column(DateTime, nullable=True)


class SiemEvent(Base):
    """Normalized immutable event collected from every Smart Port subsystem."""
    __tablename__ = "siem_events"
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, index=True)       # mqtt, http, drone, ros2, auth, sensor, network
    event_type = Column(String, index=True)
    device_id = Column(String, index=True, nullable=True)
    severity = Column(String, index=True, default="info")
    message = Column(Text)
    payload = Column(Text, nullable=True)     # JSON, retained in the data lake as the source of truth
    occurred_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    correlation_id = Column(String, nullable=True, index=True)


class Device(Base):
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True)
    device_id = Column(String, unique=True, index=True, nullable=False)
    device_type = Column(String, nullable=False)
    zone = Column(String, nullable=False)
    status = Column(String, default="registered")
    last_seen = Column(DateTime, default=datetime.datetime.utcnow)


class Drone(Base):
    __tablename__ = "drones"
    id = Column(Integer, primary_key=True)
    drone_id = Column(String, unique=True, index=True, nullable=False)
    x = Column(Float, default=0.0)
    y = Column(Float, default=0.0)
    altitude = Column(Float, default=0.0)
    battery = Column(Float, default=100.0)
    speed = Column(Float, default=0.0)
    status = Column(String, default="idle")
    mission_id = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable=False)
    report_type = Column(String, default="siem")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class LogEntry(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True)
    level = Column(String, default="info")
    message = Column(Text, nullable=False)
    source = Column(String, default="platform")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
