"""Scheduling correctness for the per-user run queue.

FCFS with a per-user serial constraint: each user is a single-server sub-queue; the
global dispatcher is FCFS over the heads, ordered by the dispatch ticket assigned at
promotion-to-head-of-line (readiness), NOT creation time.

Requires a live Postgres (see conftest.py for why SQLite cannot back these).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.database.models import Run, RunStatus, User
from apps.api.repositories.run_repository import RunRepository


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def make_user(session, tag: str) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        email=f"{tag}-{suffix}@test.io",
        username=f"{tag}-{suffix}",
        password_hash="x",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def enqueue(repo: RunRepository, user_id) -> Run:
    """Mirror the router: create the run QUEUED, then promote (immediate dispatch if
    the user's turn is free)."""
    run = await repo.create_run(method_id="dowser", params={}, user_id=user_id)
    if user_id is not None:
        await repo.promote_next_for_user(user_id)
    else:
        await repo.promote_run(run.id)
    return run


async def active_turn_count(session, user_id) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.user_id == user_id)
            .where(
                or_(
                    Run.status == RunStatus.RUNNING,
                    and_(Run.status == RunStatus.QUEUED, Run.dispatch_seq.isnot(None)),
                )
            )
        )
        or 0
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
async def test_fairness_single_slot(session):
    """MUST pass: A submits A1..A4, then B submits B1; with one worker slot the
    execution order is A1, B1, A2, A3, A4 — B1 does NOT wait behind all of A."""
    repo = RunRepository(session)
    a = await make_user(session, "a")
    b = await make_user(session, "b")

    a_runs = [await enqueue(repo, a.id) for _ in range(4)]
    b1 = await enqueue(repo, b.id)

    order = []
    for _ in range(5):
        await repo.promote_all_eligible()
        run = await repo.claim_next_run("w1", lease_seconds=120)
        assert run is not None
        order.append(run.id)
        await repo.set_result(run.id, {"ok": True})  # completes -> promotes next

    expected = [a_runs[0].id, b1.id, a_runs[1].id, a_runs[2].id, a_runs[3].id]
    assert order == expected


async def test_one_active_turn_per_user(session):
    """A single user with 4 queued runs never has more than one running; other slots
    serve other users."""
    repo = RunRepository(session)
    a = await make_user(session, "a")
    c = await make_user(session, "c")

    a_runs = [await enqueue(repo, a.id) for _ in range(4)]
    c1 = await enqueue(repo, c.id)

    await repo.promote_all_eligible()

    claimed = []
    while True:
        run = await repo.claim_next_run("w", lease_seconds=120)
        if run is None:
            break
        claimed.append(run)

    claimed_ids = {r.id for r in claimed}
    assert a_runs[0].id in claimed_ids  # A's head runs
    assert c1.id in claimed_ids  # another user's run fills another slot
    a_claimed = [r for r in claimed if r.user_id == a.id]
    assert len(a_claimed) == 1  # never two of A's runs at once
    assert len(claimed) == 2  # only the two heads are dispatch-ready


async def test_free_slot_dispatches_immediately(session):
    """A is running with a queue; B submits and dispatches immediately to a free slot
    (not blocked behind A's queued runs)."""
    repo = RunRepository(session)
    a = await make_user(session, "a")
    b = await make_user(session, "b")

    a1 = await enqueue(repo, a.id)
    await enqueue(repo, a.id)  # a2 waits behind a1

    running = await repo.claim_next_run("w", lease_seconds=120)
    assert running is not None and running.id == a1.id

    b1 = await enqueue(repo, b.id)
    nxt = await repo.claim_next_run("w", lease_seconds=120)
    assert nxt is not None and nxt.id == b1.id


async def test_promotion_on_completion(session):
    repo = RunRepository(session)
    a = await make_user(session, "a")
    a1 = await enqueue(repo, a.id)
    a2 = await enqueue(repo, a.id)

    running = await repo.claim_next_run("w", lease_seconds=120)
    assert running.id == a1.id
    assert (await repo.get_active_turn_run_for_user(a.id)).id == a1.id

    await repo.set_result(a1.id, {"ok": True})
    promoted = await repo.get_active_turn_run_for_user(a.id)
    assert promoted is not None and promoted.id == a2.id


async def test_promotion_on_cancel_active_turn(session):
    repo = RunRepository(session)
    a = await make_user(session, "a")
    a1 = await enqueue(repo, a.id)  # promoted turn
    a2 = await enqueue(repo, a.id)  # personal queue

    cancelled = await repo.cancel_queued_run(a1.id, a.id)
    assert cancelled is not None

    promoted = await repo.get_active_turn_run_for_user(a.id)
    assert promoted is not None and promoted.id == a2.id


async def test_cancel_personal_queue_item_does_not_disturb_others(session):
    repo = RunRepository(session)
    a = await make_user(session, "a")
    b = await make_user(session, "b")

    a1 = await enqueue(repo, a.id)  # A's turn
    a2 = await enqueue(repo, a.id)  # A personal queue
    a3 = await enqueue(repo, a.id)  # A personal queue
    b1 = await enqueue(repo, b.id)  # B's turn

    b_seq_before = (await repo.get_by_id(b1.id)).dispatch_seq

    cancelled = await repo.cancel_queued_run(a2.id, a.id)
    assert cancelled is not None

    # A's active turn unchanged; a3 still waiting (not promoted).
    assert (await repo.get_active_turn_run_for_user(a.id)).id == a1.id
    assert (await repo.get_by_id(a3.id)).dispatch_seq is None
    # B's dispatch ordering untouched.
    assert (await repo.get_by_id(b1.id)).dispatch_seq == b_seq_before


async def test_second_promotion_is_noop(session):
    repo = RunRepository(session)
    a = await make_user(session, "a")
    await enqueue(repo, a.id)  # promoted turn
    await enqueue(repo, a.id)  # personal queue

    assert await repo.promote_next_for_user(a.id) is None
    assert await active_turn_count(session, a.id) == 1


async def test_partial_unique_index_rejects_second_active_turn(session):
    """Directly forcing a second promoted QUEUED run for one user must be rejected by
    the partial-unique backstop."""
    repo = RunRepository(session)
    a = await make_user(session, "a")
    await enqueue(repo, a.id)  # active turn (dispatch_seq set)
    a2 = await enqueue(repo, a.id)  # personal queue

    with pytest.raises(IntegrityError):
        await session.execute(
            update(Run)
            .where(Run.id == a2.id)
            .values(dispatch_seq=func.nextval("runs_dispatch_seq"))
        )
        await session.flush()
    await session.rollback()
