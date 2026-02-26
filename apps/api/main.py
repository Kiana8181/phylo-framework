from __future__ import annotations
import asyncio
import os
import traceback

# Force UTC for datetime/zoneinfo (avoids Windows Errno 22 with DB timestamps)
if "TZ" not in os.environ:
    os.environ["TZ"] = "UTC"
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from dotenv import load_dotenv
load_dotenv()

from apps.api.config import CORS_ORIGINS
from apps.api.routers import methods as methods_router
from apps.api.routers import runs as runs_router
from apps.api.routers.runs import _pending_run_executor_loop
from apps.api.routers import files as files_router
from apps.api.auth import auth_router
from apps.api.database import init_db, close_db

app = FastAPI(title="Phylo Orchestrator")


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup and start pending-run executor."""
    # Pick up PENDING runs that were never started (e.g. after --reload or crash)
    asyncio.create_task(_pending_run_executor_loop())


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
    return err(msg, status_code=exc.status_code, data=data)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return err("Validation error", status_code=422, data=exc.errors())

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    msg = str(exc).strip() if os.environ.get("ENV") != "production" else "Internal server error"
    return err(msg or "Internal server error", status_code=500)

# Routers
app.include_router(auth_router)
app.include_router(methods_router.router)
app.include_router(runs_router.router)
app.include_router(files_router.router)