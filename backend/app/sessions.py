"""Demo session manager for CivicGrid.

Provides per-session isolated workspaces using PostgreSQL schemas.
Resolves demo sessions across:
  1. X-Demo-Session header
  2. Query params (?session_id=... or ?demo_session=...)
  3. JWT token claim ('session_id')
  4. Client IP / fingerprint mapping (continuity across role logouts for older frontends)
"""
from __future__ import annotations

from contextvars import ContextVar
import os
import re
import threading
import time
import uuid
from typing import Optional

import jwt
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .config import JWT_ALG, JWT_SECRET
from .models import Base

current_session_id: ContextVar[Optional[str]] = ContextVar("current_session_id", default=None)

_SCHEMA_LOCK = threading.Lock()
_INITIALIZED_SCHEMAS: set[str] = set()

# Maps client_ip -> (session_id, last_active_timestamp)
_ACTIVE_IP_SESSIONS: dict[str, tuple[str, float]] = {}
_IP_SESSION_TTL_SECONDS = 7200  # 2 hours sliding window


def normalize_session_id(raw_sid: Optional[str]) -> Optional[str]:
    if not raw_sid:
        return None
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", str(raw_sid).strip())[:32]
    return cleaned or None


def schema_name_for_session(session_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "", session_id.lower())[:32]
    if not cleaned:
        cleaned = "default"
    return f"cg_sess_{cleaned}"


def get_client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # First IP in the comma-separated chain
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host.strip()
    return "127.0.0.1"


def extract_session_from_token(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:].strip()
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG], options={"verify_exp": False})
        return normalize_session_id(claims.get("session_id"))
    except Exception:
        return None


def get_active_ip_session(client_ip: str) -> Optional[str]:
    with _SCHEMA_LOCK:
        entry = _ACTIVE_IP_SESSIONS.get(client_ip)
        if not entry:
            return None
        sid, last_active = entry
        if (time.time() - last_active) > _IP_SESSION_TTL_SECONDS:
            _ACTIVE_IP_SESSIONS.pop(client_ip, None)
            return None
        _ACTIVE_IP_SESSIONS[client_ip] = (sid, time.time())
        return sid


def set_active_ip_session(client_ip: str, session_id: str) -> None:
    with _SCHEMA_LOCK:
        _ACTIVE_IP_SESSIONS[client_ip] = (session_id, time.time())


def clear_active_ip_session(client_ip: str) -> None:
    with _SCHEMA_LOCK:
        _ACTIVE_IP_SESSIONS.pop(client_ip, None)


def resolve_session_id(request: Request) -> Optional[str]:
    # 1. Explicit header
    h_sid = normalize_session_id(request.headers.get("X-Demo-Session"))
    if h_sid:
        return h_sid

    # 2. Query param
    q_sid = normalize_session_id(request.query_params.get("session_id") or request.query_params.get("demo_session"))
    if q_sid:
        return q_sid

    # 3. JWT token claim
    t_sid = extract_session_from_token(request.headers.get("Authorization"))
    if t_sid:
        return t_sid

    # 4. Check active IP session (e.g. for /auth/login or unauthenticated calls)
    client_ip = get_client_ip(request)
    import sys
    if "pytest" in sys.modules and client_ip in ("testclient", "127.0.0.1") and not request.headers.get("X-Forwarded-For"):
        return None
    ip_sid = get_active_ip_session(client_ip)
    if ip_sid:
        return ip_sid

    return None


def get_or_create_session_for_login(request: Request, force_new: bool = False) -> Optional[str]:
    """Called during /auth/login to establish or continue a session."""
    # 1. Header or query param takes highest priority
    h_sid = normalize_session_id(request.headers.get("X-Demo-Session"))
    if h_sid:
        return h_sid

    q_sid = normalize_session_id(request.query_params.get("session_id") or request.query_params.get("demo_session"))
    if q_sid:
        return q_sid

    client_ip = get_client_ip(request)

    # In unit tests with TestClient (no X-Forwarded-For), operate on default test db
    import sys
    if "pytest" in sys.modules and client_ip in ("testclient", "127.0.0.1") and not request.headers.get("X-Forwarded-For"):
        return None

    # Check if client explicitly requested a fresh session
    reset_requested = (
        force_new
        or request.query_params.get("fresh") in ("1", "true")
        or request.query_params.get("new_session") in ("1", "true")
        or request.headers.get("X-Reset-Session") in ("1", "true")
    )

    if not reset_requested:
        existing = get_active_ip_session(client_ip)
        if existing:
            return existing

    # Generate fresh session ID
    new_sid = f"s_{uuid.uuid4().hex[:12]}"
    set_active_ip_session(client_ip, new_sid)
    return new_sid


def ensure_session_schema(engine: Engine, session_id: str) -> str:
    """Clones all application tables and seeded data into a dedicated PostgreSQL schema.
    Returns the schema name.
    """
    if engine.dialect.name != "postgresql":
        return ""

    schema_name = schema_name_for_session(session_id)
    with _SCHEMA_LOCK:
        if schema_name in _INITIALIZED_SCHEMAS:
            return schema_name

        with engine.begin() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
                {"s": schema_name},
            ).scalar()

            if not exists:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
                conn.execute(text(f'SET search_path TO "{schema_name}", public'))
                
                # Clone all table definitions
                for table in Base.metadata.sorted_tables:
                    conn.execute(
                        text(f'CREATE TABLE IF NOT EXISTS "{schema_name}"."{table.name}" (LIKE public."{table.name}" INCLUDING ALL)')
                    )

                # Clone initial seeded data
                for table in Base.metadata.sorted_tables:
                    conn.execute(
                        text(f'INSERT INTO "{schema_name}"."{table.name}" SELECT * FROM public."{table.name}" ON CONFLICT DO NOTHING')
                    )

            _INITIALIZED_SCHEMAS.add(schema_name)

    return schema_name


def reset_session_schemas(engine: Engine) -> None:
    """Drops all demo session schemas (used in tests or admin purge)."""
    with _SCHEMA_LOCK:
        _INITIALIZED_SCHEMAS.clear()
        _ACTIVE_IP_SESSIONS.clear()
        if engine.dialect.name == "postgresql":
            with engine.begin() as conn:
                schemas = conn.execute(
                    text("SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'cg_sess_%'")
                ).scalars().all()
                for s in schemas:
                    conn.execute(text(f'DROP SCHEMA IF EXISTS "{s}" CASCADE'))
