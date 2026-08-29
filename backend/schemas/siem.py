"""Validated REST contracts for SIEM collection and response APIs."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.siem.contracts import SOURCES, SeverityLevel


class SiemEventIn(BaseModel):
    source: str = Field(description="mqtt, http, drone, ros2, auth, sensor, or network")
    event_type: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)
    severity: SeverityLevel = SeverityLevel.INFO
    device_id: Optional[str] = Field(default=None, max_length=128)
    occurred_at: Optional[datetime] = None
    correlation_id: Optional[str] = Field(default=None, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source")
    @classmethod
    def known_source(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in SOURCES:
            raise ValueError(f"source must be one of: {', '.join(sorted(SOURCES))}")
        return value


class SiemEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str
    event_type: str
    device_id: Optional[str]
    severity: str
    message: str
    occurred_at: datetime
    correlation_id: Optional[str]


class RiskScoreOut(BaseModel):
    score: int
    level: str
    window_minutes: int
    event_count: int


class ReportRequest(BaseModel):
    window_minutes: int = Field(default=1440, ge=1, le=43200)
