"""Canonical high-level run stages and their coarse progress mapping.

Progress is only a coarse UI hint and must be tied to stage transitions.
Never increment progress on a timer; only update it when the stage changes.
"""
from __future__ import annotations

# High-level orchestration stages owned by the API/worker.
STAGE_QUEUED = "QUEUED"
STAGE_STAGING_INPUT = "STAGING_INPUT"
STAGE_PREPROCESSING = "PREPROCESSING"
STAGE_SUBMITTING_METHOD_JOB = "SUBMITTING_METHOD_JOB"
STAGE_RUNNING_METHOD = "RUNNING_METHOD"
STAGE_BUILDING_TREES = "BUILDING_TREES"
STAGE_RUNNING_ANALYSIS = "RUNNING_ANALYSIS"
STAGE_RENDERING_EXPORTS = "RENDERING_EXPORTS"
STAGE_FETCHING_RESULT = "FETCHING_RESULT"
STAGE_COMPLETED = "COMPLETED"
STAGE_CANCELLING = "CANCELLING"
STAGE_CANCELLED = "CANCELLED"
STAGE_ERROR = "ERROR"

# Coarse stage -> progress percentage. Used only on stage transitions.
STAGE_PROGRESS: dict[str, int] = {
    STAGE_QUEUED: 0,
    STAGE_STAGING_INPUT: 5,
    STAGE_PREPROCESSING: 10,
    STAGE_SUBMITTING_METHOD_JOB: 20,
    # Method-reported stages (mapped from method service job status)
    "VALIDATING_REQUEST": 25,
    "READING_INPUT": 30,
    "PREPARING_INPUT": 35,
    "FORMATTING_CLONES": 40,
    STAGE_RUNNING_METHOD: 45,
    STAGE_BUILDING_TREES: 50,
    STAGE_RUNNING_ANALYSIS: 70,
    STAGE_RENDERING_EXPORTS: 90,
    STAGE_FETCHING_RESULT: 95,
    STAGE_COMPLETED: 100,
    # Terminal non-success stages keep current value; do not imply completion.
    STAGE_CANCELLING: None,  # type: ignore[dict-item]
    STAGE_CANCELLED: None,  # type: ignore[dict-item]
    STAGE_ERROR: None,  # type: ignore[dict-item]
}


def progress_for_stage(stage: str | None, *, default: int | None = None) -> int | None:
    """Return the coarse progress for a stage, or default when unknown/non-success.

    Returns None when the stage should not change the existing progress
    (e.g. CANCELLING/ERROR), so callers can preserve the current value.
    """
    if not stage:
        return default
    if stage in STAGE_PROGRESS:
        return STAGE_PROGRESS[stage]
    return default
