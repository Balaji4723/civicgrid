from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import CORS_ORIGINS
from .errors import ServiceError
from .routers import admin, audits, auth, disposal_exception, discrepancy, evidence, final_disposition, geo, handoff, loads, processing, sanitation, seeded, worker

app = FastAPI(title="CivicGrid API", version="0.1-demo",
              description="Demo prototype. Real: Cross-Check Engine, Discrepancy state machine, hash-chained event log. Everything else is seeded/simplified.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



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
         audits.router, processing.router, handoff.router, final_disposition.router, disposal_exception.router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"ok": True}
