"""Authenticated REST API for the Smart Port SIEM."""
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.dependencies import CurrentUser, get_siem_service
from backend.schemas import ReportRequest, RiskScoreOut, SiemEventIn, SiemEventOut
from backend.siem.platform import SmartPortSiem
from pathlib import Path

router = APIRouter(prefix="/api/v1/siem", tags=["SIEM"])


@router.post("/events", status_code=202)
def collect_event(payload: SiemEventIn, service: SmartPortSiem = Depends(get_siem_service), _: dict = CurrentUser):
    return service.collect(payload)


@router.get("/events", response_model=list[SiemEventOut])
def list_events(limit: int = Query(100, ge=1, le=1000), service: SmartPortSiem = Depends(get_siem_service), _: dict = CurrentUser):
    return service.events(limit)


@router.get("/risk", response_model=RiskScoreOut)
def risk_score(service: SmartPortSiem = Depends(get_siem_service), _: dict = CurrentUser):
    return service.risk.calculate(service.db)


@router.get("/incidents")
def open_incidents(service: SmartPortSiem = Depends(get_siem_service), _: dict = CurrentUser):
    return service.open_incidents()


@router.post("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: int, service: SmartPortSiem = Depends(get_siem_service), _: dict = CurrentUser):
    incident = service.resolve_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"id": incident.id, "status": incident.status}


@router.get("/reports")
def list_reports(_: dict = CurrentUser):
    return [{"filename": path.name, "size": path.stat().st_size} for path in sorted(Path("reports").glob("*.pdf"), reverse=True)]

@router.post("/reports")
def generate_report(payload: ReportRequest, service: SmartPortSiem = Depends(get_siem_service), _: dict = CurrentUser):
    return {"filename": service.report(payload.window_minutes), "status": "generated"}
