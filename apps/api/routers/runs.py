from __future__ import annotations

import os
import json
import uuid
from typing import Optional
from datetime import datetime

import aiofiles
from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from apps.api.database import get_db
from apps.api.database.models.run import Run, RunStatus
from apps.api.database.models.result import Result
from apps.api.config import method_service_url
from apps.api.services.queue import enqueue_run, get_queue_status
from apps.api.auth.router import fastapi_users
from apps.api.database.models.user import User

router = APIRouter(prefix="/runs", tags=["runs"])

DEFAULT_RUNS_DIR = os.path.join(os.getcwd(), "runtime", "runs")
RUNS_DIR = os.environ.get("RUNS_DIR", DEFAULT_RUNS_DIR)
os.makedirs(RUNS_DIR, exist_ok=True)


def _public_status(run: Run) -> dict:
    """Convert run to public status format."""
    return {
        "status": run.status.value,
        "progress": run.progress,
        "message": run.message,
    }


@router.post("")
async def create_run(
    method: str = Query(..., description="Method ID (e.g., 'dowser')"),
    params: str = Form("{}", description="JSON string of parameters"),
    file: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(fastapi_users.current_user(optional=True)),
):
    """Create a new run."""
    base = method_service_url(method)
    if not base:
        raise HTTPException(400, f"No service URL configured for method '{method}'. Set METHOD_{method.upper()}_URL.")

    try:
        p = json.loads(params or "{}")
        if not isinstance(p, dict):
            raise ValueError("params must be a JSON object")
    except Exception as e:
        raise HTTPException(400, f"Invalid params JSON: {e}")

    run_id = uuid.uuid4()
    run_dir = os.path.join(RUNS_DIR, str(run_id))
    os.makedirs(run_dir, exist_ok=True)

    file_path = None
    if file is not None:
        dst = os.path.join(run_dir, file.filename or "upload")
        try:
            async with aiofiles.open(dst, "wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)  # 1MB
                    if not chunk:
                        break
                    await out.write(chunk)
            file_path = dst
        except Exception as e:
            raise HTTPException(500, f"Failed to save upload: {e}")

    # Create run in database
    run = Run(
        id=run_id,
        user_id=user.id if user else None,
        method_id=method,
        status=RunStatus.PENDING,
        progress=0,
        message="Queued",
        file_path=file_path,
        params=p,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    # Enqueue the task
    enqueue_run(str(run_id))

    return {"run_id": str(run_id)}


@router.get("")
async def list_runs(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    method_id: Optional[str] = Query(None, description="Filter by method ID"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    session: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(fastapi_users.current_user(optional=True)),
):
    """List runs with pagination and filtering."""
    query = select(Run)
    
    # Apply filters
    if user_id:
        query = query.where(Run.user_id == uuid.UUID(user_id))
    elif user:
        # If user is authenticated, show only their runs
        query = query.where(Run.user_id == user.id)
    
    if status:
        try:
            status_enum = RunStatus(status.upper())
            query = query.where(Run.status == status_enum)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")
    
    if method_id:
        query = query.where(Run.method_id == method_id)
    
    # Get total count
    from sqlalchemy import func
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    offset = (page - 1) * limit
    query = query.order_by(Run.created_at.desc()).offset(offset).limit(limit)
    
    # Execute query
    result = await session.execute(query)
    runs = result.scalars().all()
    
    return {
        "items": [
            {
                "id": str(run.id),
                "method_id": run.method_id,
                "status": run.status.value,
                "progress": run.progress,
                "message": run.message,
                "created_at": run.created_at.isoformat() if run.created_at else None,
            }
            for run in runs
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/{run_id}/status")
async def run_status(
    run_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Get run status."""
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, "Invalid run ID format")
    
    result = await session.execute(select(Run).where(Run.id == run_uuid))
    run = result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(404, "Run not found")
    
    return _public_status(run)


@router.get("/{run_id}/result")
async def run_result(
    run_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Get run result."""
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, "Invalid run ID format")
    
    result = await session.execute(
        select(Result).where(Result.run_id == run_uuid)
    )
    result_obj = result.scalar_one_or_none()
    
    if not result_obj:
        # Check if run exists
        run_result = await session.execute(select(Run).where(Run.id == run_uuid))
        run = run_result.scalar_one_or_none()
        if not run:
            raise HTTPException(404, "Run not found")
        if run.status != RunStatus.DONE:
            raise HTTPException(409, "Run not finished")
        return {"ok": False}
    
    return result_obj.result_data


@router.delete("/{run_id}")
async def cancel_run(
    run_id: str,
    session: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(fastapi_users.current_user(optional=True)),
):
    """Cancel a run (if it's pending)."""
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, "Invalid run ID format")
    
    result = await session.execute(select(Run).where(Run.id == run_uuid))
    run = result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(404, "Run not found")
    
    # Check authorization
    if user and run.user_id != user.id:
        raise HTTPException(403, "Not authorized to cancel this run")
    
    # Only allow canceling pending runs
    if run.status != RunStatus.PENDING:
        raise HTTPException(400, f"Cannot cancel run with status {run.status.value}")
    
    run.status = RunStatus.ERROR
    run.message = "Cancelled by user"
    run.progress = 100
    run.finished_at = datetime.utcnow()
    
    await session.commit()
    
    return {"message": "Run cancelled"}


@router.get("/queue/status")
async def queue_status():
    """Get queue status."""
    return get_queue_status()
