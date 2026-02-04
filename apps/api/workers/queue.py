from __future__ import annotations

import os
from redis import Redis
from rq import Queue
from typing import Optional

from apps.api.config import REDIS_URL, RQ_QUEUE_NAME

# Create Redis connection
redis_conn = Redis.from_url(REDIS_URL, decode_responses=True)

# Create queue
default_queue = Queue(RQ_QUEUE_NAME, connection=redis_conn)


def get_queue(name: Optional[str] = None) -> Queue:
    """Get RQ queue by name."""
    if name is None:
        return default_queue
    return Queue(name, connection=redis_conn)


def enqueue_task(task_func, *args, **kwargs):
    """Enqueue a task to the default queue."""
    return default_queue.enqueue(task_func, *args, **kwargs)


def get_queue_status() -> dict:
    """Get status of the default queue."""
    return {
        "name": default_queue.name,
        "count": len(default_queue),
        "failed": len(default_queue.failed_job_registry),
    }

