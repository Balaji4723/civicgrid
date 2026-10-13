from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import CORS_ORIGINS
from .errors import ServiceError
from .routers import admin, audits, auth, civicai, disposal_exception, discrepancy, evidence, final_disposition, geo, handoff, loads, processing, sanitation, seeded, worker

app = FastAPI(title="CivicGrid API", version="0.1-demo",
              description="Demo prototype. Real: Cross-Check Engine, Discrepancy state machine, hash-chained event log. Everything else is seeded/simplified.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS if o.strip()] + ["https://civicgrid-ashy.vercel.app"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?|https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def session_isolation_middleware(request: Request, call_next):
    from .sessions import current_session_id, resolve_session_id, get_or_create_session_for_login
    if request.url.path == "/auth/login" and request.method == "POST":
        sid = get_or_create_session_for_login(request)
    else:
        sid = resolve_session_id(request)

    token = current_session_id.set(sid)
    try:
        response = await call_next(request)
        if sid:
            response.headers["X-Demo-Session"] = sid
        return response
    finally:
        current_session_id.reset(token)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(self), camera=(self)"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response



@app.exception_handler(ServiceError)
async def service_error_handler(_: Request, exc: ServiceError):
    return JSONResponse(status_code=exc.status_code,
                        content={"detail": {"error": exc.code, "message": exc.message, **exc.extra}})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    """Same 422 shape as FastAPI's default, but never echoes the offending input back.

    The default handler puts `input` in the response; for a body like {"latitude": NaN} that value is not valid
    JSON, so serialising the *error* crashed and the client saw a 500 instead of a 422 (found by test_geo.py).
    """
    return JSONResponse(status_code=422, content={"detail": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]})


for r in (auth.router, worker.router, loads.router, discrepancy.router, admin.router, seeded.router, geo.router, sanitation.router, evidence.router,
         audits.router, processing.router, handoff.router, final_disposition.router, disposal_exception.router, civicai.router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/demo-session")
def demo_session_info(request: Request):
    from .sessions import current_session_id, get_client_ip
    sid = current_session_id.get()
    return {"session_id": sid, "client_ip": get_client_ip(request)}


@app.post("/demo-session/reset")
def demo_session_reset(request: Request):
    from .db import engine
    from .sessions import ensure_session_schema, get_client_ip, set_active_ip_session
    import uuid
    client_ip = get_client_ip(request)
    new_sid = f"s_{uuid.uuid4().hex[:12]}"
    set_active_ip_session(client_ip, new_sid)
    ensure_session_schema(engine, new_sid)
    return {"session_id": new_sid, "message": "Demo workspace reset to clean seeded state."}
