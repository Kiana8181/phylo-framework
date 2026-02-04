from __future__ import annotations

from typing import Optional
from apps.api.workers.queue import get_queue, get_queue_status
from apps.api.workers.tasks import execute_method_task


def enqueue_run(run_id: str, queue_name: Optional[str] = None) -> None:
    """Enqueue a run task."""
    queue = get_queue(queue_name)
    queue.enqueue(execute_method_task, str(run_id))


def cancel_run(run_id: str) -> bool:
    """Cancel a run if it's in the queue."""
    # Note: RQ doesn't have built-in cancel for running jobs
    # This would need to be implemented with job registry
    # For now, we'll just mark it as cancelled in the database
    return False  # Placeholder

