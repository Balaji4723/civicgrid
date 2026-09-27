"""Minimal JWT auth with four roles. Demo-grade: no refresh tokens, lockout or rate limiting (out of scope)."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import JWT_ALG, JWT_EXPIRE_MINUTES, JWT_SECRET
from .db import get_db
from .models import Role, User, utcnow

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = os.urandom(8).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 60_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, digest = stored.split("$")
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 60_000).hex()
    return hmac.compare_digest(candidate, digest)


def make_token(user: User) -> str:
    claims = {"sub": str(user.id), "role": user.role.value, "exp": utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)}
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALG)


def current_user(creds: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(401, {"error": "NOT_AUTHENTICATED", "message": "Sign in first."})
    try:
        claims = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(401, {"error": "BAD_TOKEN", "message": "Session expired or invalid. Sign in again."})
    user = db.get(User, int(claims["sub"]))
    if not user:
        raise HTTPException(401, {"error": "BAD_TOKEN", "message": "Unknown user."})
    return user


def get_user_capabilities(user: User) -> list[str]:
    if user.capability:
        return [c.strip().upper() for c in user.capability.split(",") if c.strip()]
    if user.role == Role.FACILITY:
        u = (user.username or "").lower()
        if "ops" in u or "proc" in u:
            return ["PROCESSING"]
        if "facility2" in u or "auditor" in u or "verifier" in u:
            return ["INDEPENDENT_VERIFIER"]
        if "facility1" in u or "receiving" in u or "intake" in u:
            return ["RECEIVING"]
        return ["RECEIVING"]
    return []


def require_roles(*roles: Role):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, {"error": "FORBIDDEN", "message": f"Requires role: {', '.join(r.value for r in roles)}."})
        return user
    return dep


def require_capability(capability: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role != Role.FACILITY:
            raise HTTPException(403, {"error": "FORBIDDEN", "message": f"Requires facility capability: {capability}."})
        caps = get_user_capabilities(user)
        if capability.upper() not in caps:
            raise HTTPException(403, {"error": "FORBIDDEN", "message": f"Requires facility capability: {capability} (user has: {', '.join(caps) or 'none'})."})
        return user
    return dep

