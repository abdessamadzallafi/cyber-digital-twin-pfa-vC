from pydantic import BaseModel
from typing import Optional

class SensorReadingOut(BaseModel):
    device_id: str
    type: str
    value: Optional[float]
    status: Optional[str]
    people_count: Optional[int]
    timestamp: float

class AlertOut(BaseModel):
    device_id: str
    alert_type: str
    message: str
    timestamp: float