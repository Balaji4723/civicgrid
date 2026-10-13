from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import check_login_rate_limit, current_user, make_token, record_failed_login, record_successful_login, verify_password
from ..db import get_db
from ..models import User

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=128)


def ser_user(u: User) -> dict:
    return {"id": u.id, "username": u.username, "name": u.name, "role": u.role.value,
            "worker_id": u.worker_id, "household_id": u.household_id, "facility_id": u.facility_id,
            "capability": u.capability}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if (request and request.client) else "127.0.0.1"
    rate_key = f"{client_ip}:{body.username.strip().lower()}"
    check_login_rate_limit(rate_key)

    user = db.execute(select(User).where(User.username == body.username.strip())).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        record_failed_login(rate_key)
        raise HTTPException(401, {"error": "BAD_CREDENTIALS", "message": "Wrong username or password."})

    record_successful_login(rate_key)
    from ..sessions import get_or_create_session_for_login, current_session_id
    session_id = current_session_id.get() or get_or_create_session_for_login(request)
    return {
        "access_token": make_token(user, session_id=session_id),
        "token_type": "bearer",
        "user": ser_user(user),
        "session_id": session_id,
    }


@router.get("/me")
def me(user: User = Depends(current_user)):
    return ser_user(user)
