from __future__ import annotations
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from dotenv import load_dotenv
load_dotenv()

from apps.api.config import CORS_ORIGINS
from apps.api.routers import methods as methods_router
from apps.api.routers import runs as runs_router

app = FastAPI(title="Phylo Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

def err(message: str, status_code: int = 400, data=None):
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "message": message, "data": data},
    )

# Normalize ALL errors
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, list):
        msg = detail[0].get("msg") if detail and isinstance(detail[0], dict) else str(detail)
    elif isinstance(detail, dict):
        msg = detail.get("message") or detail.get("detail") or str(detail)
    else:
        msg = str(detail)
    return err(msg, status_code=exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return err("Validation error", status_code=422, data=exc.errors())

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return err("Internal server error", status_code=500)

# Routers
app.include_router(methods_router.router)
app.include_router(runs_router.router)
