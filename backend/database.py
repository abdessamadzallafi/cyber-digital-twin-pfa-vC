from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
import datetime
from smart_port.config import settings

DATABASE_URL = settings.database_url
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    poolclass=NullPool   # évite les erreurs de connexions concurrentes en SQLite
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class SensorReading(Base):
    __tablename__ = "sensor_readings"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    type = Column(String)
    value = Column(Float, nullable=True)          # pour température, humidité, vibration, fumée
    unit = Column(String, nullable=True)
    status = Column(String, nullable=True)        # pour barrière, présence, robot
    people_count = Column(Integer, nullable=True) # pour caméra
    latitude = Column(Float, nullable=True)       # pour GPS, ou position y du robot
    longitude = Column(Float, nullable=True)      # pour GPS, ou batterie du robot
    timestamp = Column(Float)
    received_at = Column(DateTime, default=datetime.datetime.utcnow)
    # Nouvelles colonnes réseau
    ip_src = Column(String, nullable=True)
    mac_src = Column(String, nullable=True)
    port_src = Column(Integer, nullable=True)
    packet_size = Column(Integer, nullable=True)

class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String)
    alert_type = Column(String)   # flood, unknown_device, bad_token, wrong_topic, network_flood, unknown_ip, ml_anomaly
    message = Column(Text)
    timestamp = Column(Float)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    severity = Column(String, nullable=True)   # low, medium, high

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
    device_id = Column(String)         # appareil concerné
    robot_id = Column(String)
    target_x = Column(Float, nullable=True)
    target_y = Column(Float, nullable=True)
    status = Column(String, default="created")   # created, sent, in_progress, completed
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    anomaly_type = Column(String)
    severity = Column(String)          # low, medium, high, critical
    status = Column(String, default="open")  # open, investigating, resolved
    description = Column(Text)
    robot_mission_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


# Création de toutes les tables (si elles n'existent pas)
Base.metadata.create_all(bind=engine)
