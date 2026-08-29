"""FastAPI interface for autonomous-drone missions and telemetry."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.dependencies import CurrentUser
from backend.ros.drone_manager import drone_manager

router = APIRouter(prefix="/api/v1/drone", tags=["Autonomous Drone"])


class MissionRequest(BaseModel):
    target_device: str = Field(min_length=1, max_length=128)
    mission_type: str = "inspection"
    priority: str = "medium"


class TelemetryRequest(BaseModel):
    x: float | None = None
    y: float | None = None
    altitude: float | None = None
    battery: float | None = Field(default=None, ge=0, le=100)
    heading: float | None = None
    status: str | None = None
    mission_id: str | None = None
    timestamp: float | None = None


@router.get("/status")
def drone_status():
    return drone_manager.status()


@router.post("/missions")
def create_drone_mission(payload: MissionRequest, _: dict = CurrentUser):
    try:
        return drone_manager.create_inspection(payload.target_device, payload.mission_type, payload.priority).__dict__
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/missions/start")
def start_drone_mission(_: dict = CurrentUser):
    try:
        return drone_manager.start()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/missions/return-home")
def return_drone_home(_: dict = CurrentUser):
    return drone_manager.return_home()


@router.post("/telemetry")
def publish_drone_telemetry(payload: TelemetryRequest, _: dict = CurrentUser):
    return drone_manager.update_telemetry(payload.model_dump(exclude_none=True))


@router.post("/camera/start")
def start_camera_stream(url: str | None = None, _: dict = CurrentUser):
    return drone_manager.camera_start(url)


@router.post("/tick")
def advance_simulation(step: float = 1.0, _: dict = CurrentUser):
    return drone_manager.tick(max(0.01, min(step, 30.0)))
