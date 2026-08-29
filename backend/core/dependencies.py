"""FastAPI dependency providers used by every versioned API route."""
from collections.abc import Generator
from fastapi import Depends
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.database import SessionLocal
from backend.services.platform_service import PlatformService
from backend.siem.platform import SmartPortSiem


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_platform_service(db: Session = Depends(get_db)) -> PlatformService:
    return PlatformService(db)


def get_siem_service(db: Session = Depends(get_db)) -> SmartPortSiem:
    return SmartPortSiem(db)


CurrentUser = Depends(get_current_user)
