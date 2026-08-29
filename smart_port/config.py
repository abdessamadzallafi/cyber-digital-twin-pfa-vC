"""Canonical environment-driven configuration for the Smart Port platform.

Environment variables can override every deployment-sensitive value, keeping the
prototype usable locally while allowing an industrial deployment configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    # ------------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------------
    mqtt_host: str = os.getenv("SMART_PORT_MQTT_HOST", "localhost")
    mqtt_port: int = int(os.getenv("SMART_PORT_MQTT_PORT", "1883"))
    mqtt_tls: bool = os.getenv("SMART_PORT_MQTT_TLS", "false").lower() == "true"
    mqtt_ca_file: str = os.getenv(
        "SMART_PORT_MQTT_CA_FILE",
        "certs/ca.crt",
    )
    mqtt_qos: int = int(os.getenv("SMART_PORT_MQTT_QOS", "1"))

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = os.getenv("SMART_PORT_DATABASE_URL", "sqlite:///./digital_twin.db")

    # ------------------------------------------------------------------
    # Data lake
    # ------------------------------------------------------------------
    data_lake_path: str = os.getenv("SMART_PORT_DATA_LAKE_PATH", "data_lake")

    # ------------------------------------------------------------------
    # HTTP API
    # ------------------------------------------------------------------
    api_host: str = os.getenv("SMART_PORT_API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("SMART_PORT_API_PORT", "8000"))
    cors_origins: tuple[str, ...] = tuple(filter(None, os.getenv("SMART_PORT_CORS_ORIGINS", "*").split(",")))

    # ------------------------------------------------------------------
    # UDP
    # ------------------------------------------------------------------
    udp_host: str = os.getenv("SMART_PORT_UDP_HOST", "0.0.0.0")
    udp_port: int = int(os.getenv("SMART_PORT_UDP_PORT", "9000"))

    # ------------------------------------------------------------------
    # Security / JWT
    # ------------------------------------------------------------------
    jwt_secret: str = os.getenv("SMART_PORT_JWT_SECRET", "")
    demo_admin_password: str = os.getenv("SMART_PORT_DEMO_ADMIN_PASSWORD", "")
    demo_operator_password: str = os.getenv("SMART_PORT_DEMO_OPERATOR_PASSWORD", "")
    environment: str = os.getenv("SMART_PORT_ENV", "development")

    # ------------------------------------------------------------------
    # Drone runtime
    # ------------------------------------------------------------------
    drone_id: str = os.getenv("SMART_PORT_DRONE_ID", "drone_01")
    drone_token: str = os.getenv("SMART_PORT_DRONE_TOKEN", "")
    drone_telemetry_interval: float = float(os.getenv("SMART_PORT_DRONE_TELEMETRY_INTERVAL", "2"))
    drone_mission_cooldown_seconds: int = int(os.getenv("SMART_PORT_DRONE_MISSION_COOLDOWN_SECONDS", "60"))

    # ------------------------------------------------------------------
    # Incident / correlation
    # ------------------------------------------------------------------
    incident_dedup_window_seconds: int = int(os.getenv("SMART_PORT_INCIDENT_DEDUP_WINDOW_SECONDS", "300"))

    # ------------------------------------------------------------------
    # Runtime / UX
    # ------------------------------------------------------------------
    websocket_queue_size: int = int(os.getenv("SMART_PORT_WEBSOCKET_QUEUE_SIZE", "1000"))
    log_level: str = os.getenv("SMART_PORT_LOG_LEVEL", "INFO")

    def validate_for_runtime(self) -> None:
        if self.environment.lower() == "production" and self.jwt_secret == "ma_cle_secrete_pour_demo":
            raise RuntimeError("SMART_PORT_JWT_SECRET must be set to a non-demo secret in production")
        if self.environment.lower() != "production":
            return
        missing = [name for name, value in {
            "SMART_PORT_JWT_SECRET": self.jwt_secret,
            "SMART_PORT_DEMO_ADMIN_PASSWORD": self.demo_admin_password,
            "SMART_PORT_DEMO_OPERATOR_PASSWORD": self.demo_operator_password,
            "SMART_PORT_DRONE_TOKEN": self.drone_token,
        }.items() if not value]
        if missing:
            raise RuntimeError(f"Missing required runtime configuration: {', '.join(missing)}")


settings = Settings()
