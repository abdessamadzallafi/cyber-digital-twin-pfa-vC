"""API contract for stateless access to the multi-domain prediction service."""
from typing import Any
from pydantic import BaseModel, Field


class AIPredictionRequest(BaseModel):
    telemetry: dict[str, Any] = Field(description="Normalized device, drone, or sensor telemetry")
    network: dict[str, float] = Field(default_factory=dict, description="packet_count, bytes_total, avg_interval, throughput")
