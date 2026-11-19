"""Versioned HTTP API. Thin handlers delegate all business work to services."""
from fastapi import APIRouter, Depends, Query

from backend.core.dependencies import CurrentUser, get_platform_service
from backend.schemas import DeviceOut, TelemetryIn
from backend.services import PlatformService
from smart_port.data.data_lake import lake_summary

router = APIRouter(prefix="/api/v1", tags=["Smart Port v1"])


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(service: PlatformService = Depends(get_platform_service), _: dict = CurrentUser):
    return service.list_devices()


@router.post("/telemetry", status_code=202)
def ingest_telemetry(payload: TelemetryIn, service: PlatformService = Depends(get_platform_service), _: dict = CurrentUser):
    return service.ingest_telemetry(payload, transport="http")


@router.get("/devices/{device_id}/telemetry")
def telemetry_history(device_id: str, limit: int = Query(100, ge=1, le=1000),
                      service: PlatformService = Depends(get_platform_service), _: dict = CurrentUser):
    return service.device_history(device_id, limit)


@router.get("/devices/{device_id}/health")
def device_health(device_id: str,
                  service: PlatformService = Depends(get_platform_service),
                  _: dict = CurrentUser):
    return service.device_health(device_id)


@router.get("/datalake")
def datalake(_: dict = CurrentUser):
    return {"format": "jsonl", "retention": "append-only", "streams": lake_summary()}
