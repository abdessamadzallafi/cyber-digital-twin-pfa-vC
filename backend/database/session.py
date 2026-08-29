"""SQLAlchemy engine and session factory; no API concerns belong here."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from backend.core.config import settings

_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _sqlite else {},
    poolclass=NullPool if _sqlite else None,
    pool_pre_ping=not _sqlite,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
