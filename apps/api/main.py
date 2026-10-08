from __future__ import annotations
import os

# Force UTC for datetime/zoneinfo (avoids Windows Errno 22 with DB timestamps)
if "TZ" not in os.environ:
    os.environ["TZ"] = "UTC"
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from dotenv import load_dotenv
load_dotenv()

from apps.api.config import API_DOCS_ENABLED, CORS_ORIGINS, IS_PRODUCTION
from apps.api.security.errors import log_internal_error
from apps.api.security.production_config import enforce_production_config

# Refuse to serve production traffic on missing, default or weak secrets. Runs
# before the routers (and the JWT signing key) are imported, so a bad
# configuration stops the process instead of starting a vulnerable API.
enforce_production_config()

from apps.api.routers import methods as methods_router
from apps.api.routers import runs as runs_router
from apps.api.routers import files as files_router
from apps.api.routers import uploads as uploads_router
from apps.api.routers import datasets as datasets_router
from apps.api.routers import artifacts as artifacts_router
from apps.api.auth import auth_router
from apps.api.database import init_db, close_db

app = FastAPI(
    title="Phylo Orchestrator",
    # The interactive docs describe every route; keep them off the public
    # internet in production unless API_DOCS_ENABLED=true.
    docs_url="/docs" if API_DOCS_ENABLED else None,
    redoc_url="/redoc" if API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
)


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connections on shutdown."""
    await close_db()


@app.get("/health")
async def health():
    """No DB, no auth. Use this to verify the API is up."""
    return {"status": "ok", "service": "phylo-api"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

def err(message: str, status_code: int = 400, data=None):
    msg = (message or "Internal server error").strip() or "Internal server error"
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "message": msg, "data": data},
    )

# Normalize ALL errors
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, list):
        msg = (detail[0].get("msg") if detail and isinstance(detail[0], dict) else str(detail)) or "Error"
        data = None
    elif isinstance(detail, dict):
        msg = detail.get("message") or detail.get("detail") or str(detail) or "Error"
        data = detail  # e.g. 409 RUN_IN_PROGRESS returns run_id, status, etc.
    else:
        msg = str(detail) if detail else "Error"
        data = None
    response = err(msg, status_code=exc.status_code, data=data)
    if exc.headers:
        response.headers.update(exc.headers)
    return response

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return err("Validation error", status_code=422, data=exc.errors())

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # The real cause goes to the server log under an error id; production
    # clients only ever see a fixed message plus that id.
    error_id = log_internal_error(
        "Unhandled error", exc, context=f"{request.method} {request.url.path}"
    )
    msg = "Internal server error" if IS_PRODUCTION else (str(exc).strip() or "Internal server error")
    return err(msg, status_code=500, data={"error_id": error_id})

# Routers
app.include_router(auth_router)
app.include_router(methods_router.router)
app.include_router(runs_router.router)
app.include_router(files_router.router)
app.include_router(uploads_router.router)
app.include_router(datasets_router.router)
app.include_router(artifacts_router.router)
