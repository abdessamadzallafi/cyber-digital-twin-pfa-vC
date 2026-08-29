# backend/auth.py
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
# Use secure password hashing via passlib/bcrypt.
from passlib.context import CryptContext
from backend.core.config import settings
from backend.logger import logger

SECRET_KEY = settings.jwt_secret
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Use bcrypt for password hashing; it salts each hash and is timing-safe.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Store hashed demo passwords. Clear-text passwords are never stored or logged.
# Fallback to deterministic local defaults when env vars are absent so local
# development remains usable without a .env file.
demo_admin_password = settings.demo_admin_password or "admin"
demo_operator_password = settings.demo_operator_password or "operateur"
fake_users_db = {
    "admin": {
        "username": "admin",
        "hashed_password": pwd_context.hash(demo_admin_password),
        "role": "admin"
    },
    "operateur": {
        "username": "operateur",
        "hashed_password": pwd_context.hash(demo_operator_password),
        "role": "user"
    }
}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

def _audit_authentication(username: str, success: bool) -> None:
    """Best-effort audit trail; login availability never depends on audit storage."""
    try:
        from backend.database import SessionLocal
        from backend.schemas.siem import SiemEventIn
        from backend.siem.platform import SmartPortSiem
        db = SessionLocal()
        try:
            SmartPortSiem(db).collect(SiemEventIn(
                source="auth", event_type="login_success" if success else "login_failed",
                severity="info" if success else "medium",
                message=f"Authentication {'succeeded' if success else 'failed'} for {username}", device_id=username))
        finally:
            db.close()
    except Exception:
        logger.exception("Authentication audit failed")

def authenticate_user(username: str, password: str):
    user = fake_users_db.get(username)
    if not user or not pwd_context.verify(password, user["hashed_password"]):
        _audit_authentication(username, False)
        return None
    _audit_authentication(username, True)
    return user

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Token invalide")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")
    user = fake_users_db.get(username)
    if user is None:
        raise HTTPException(status_code=401, detail="Utilisateur inconnu")
    return user
