"""Unit tests for the coarse stage->progress mapping.

These verify progress is a pure function of the stage (no timers) and that
terminal non-success stages never imply completion.

Run from the repo root:
    .venv/bin/python -m pytest apps/api/tests/test_stage_map.py
"""
from apps.api.services import stage_map
from apps.api.services.stage_map import progress_for_stage


def test_progress_increases_monotonically_through_pipeline():
    ordered = [
        stage_map.STAGE_QUEUED,
        stage_map.STAGE_STAGING_INPUT,
        stage_map.STAGE_PREPROCESSING,
        stage_map.STAGE_SUBMITTING_METHOD_JOB,
        stage_map.STAGE_BUILDING_TREES,
        stage_map.STAGE_RUNNING_ANALYSIS,
        stage_map.STAGE_RENDERING_EXPORTS,
        stage_map.STAGE_FETCHING_RESULT,
        stage_map.STAGE_COMPLETED,
    ]
    values = [progress_for_stage(s) for s in ordered]
    assert values[0] == 0
    assert values[-1] == 100
    # Strictly non-decreasing across the happy-path pipeline.
    assert all(b >= a for a, b in zip(values, values[1:]))


def test_terminal_non_success_stages_do_not_change_progress():
    # CANCELLING/CANCELLED/ERROR return None so callers keep the current value
    # and never imply a successful 100%.
    for stage in (stage_map.STAGE_CANCELLING, stage_map.STAGE_CANCELLED, stage_map.STAGE_ERROR):
        assert progress_for_stage(stage) is None


def test_unknown_or_missing_stage_returns_default():
    assert progress_for_stage(None) is None
    assert progress_for_stage(None, default=42) == 42
    assert progress_for_stage("NOT_A_REAL_STAGE", default=13) == 13


def test_method_reported_stages_are_mapped():
    # Stages reported by method services should resolve to a coarse percentage.
    assert progress_for_stage("VALIDATING_REQUEST") == 25
    assert progress_for_stage("FORMATTING_CLONES") == 40
