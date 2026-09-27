from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, make_token, verify_password
from ..db import get_db
from ..models import User

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


def ser_user(u: User) -> dict:
    return {"id": u.id, "username": u.username, "name": u.name, "role": u.role.value,
            "worker_id": u.worker_id, "household_id": u.household_id, "facility_id": u.facility_id,
            "capability": u.capability}



@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, {"error": "BAD_CREDENTIALS", "message": "Wrong username or password."})
    return {"access_token": make_token(user), "token_type": "bearer", "user": ser_user(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return ser_user(user)
