"""JWT authentication — enabled when AUTH_USERNAME, AUTH_PASSWORD, and AUTH_SECRET are set."""

import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException
from pydantic import BaseModel

IST = timezone(timedelta(hours=5, minutes=30))
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

PUBLIC_ROUTES = {
    ("GET", "/health"),
    ("GET", "/config"),
    ("GET", "/docs"),
    ("GET", "/openapi.json"),
    ("GET", "/redoc"),
    ("POST", "/auth/login"),
    ("GET", "/"),
}

# Paths that must load before a user can authenticate — static assets + the login page itself
_STATIC_PREFIXES = ("/_next/", "/favicon", "/static/", "/login")


class LoginRequest(BaseModel):
    username: str
    password: str


def auth_enabled() -> bool:
    return bool(
        os.getenv("AUTH_USERNAME")
        and os.getenv("AUTH_PASSWORD")
        and os.getenv("AUTH_SECRET")
    )


def is_public_route(method: str, path: str) -> bool:
    if (method, path) in PUBLIC_ROUTES:
        return True
    if path.startswith("/docs") or path.startswith("/redoc"):
        return True
    if any(path.startswith(p) for p in _STATIC_PREFIXES):
        return True
    if path.endswith((".png", ".jpg", ".jpeg", ".svg", ".ico", ".css", ".js", ".woff", ".woff2", ".txt")):
        return True
    return False


def verify_credentials(username: str, password: str) -> bool:
    expected_user = os.getenv("AUTH_USERNAME", "")
    expected_pass = os.getenv("AUTH_PASSWORD", "")
    user_ok = secrets.compare_digest(username, expected_user)
    pass_ok = secrets.compare_digest(password, expected_pass)
    return user_ok and pass_ok


def create_token(username: str) -> str:
    secret = os.environ["AUTH_SECRET"]
    expire = datetime.now(IST) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def verify_token(token: str) -> str:
    secret = os.environ["AUTH_SECRET"]
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        return payload["sub"]
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
