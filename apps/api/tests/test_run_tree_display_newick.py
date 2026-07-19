"""Round-trip persistence for the optional per-tree ``display_newick`` column.

Requires a live Postgres (see conftest.py). A tree WITH ``display_newick`` and a
tree WITHOUT it must both persist and read back correctly, the latter as ``None``
so old runs / other methods fall back to the canonical newick on download.
"""
from __future__ import annotations

import uuid

import pytest

from apps.api.database.models import User
from apps.api.repositories.run_repository import RunRepository
from apps.api.repositories.run_tree_repository import RunTreeRepository


async def _make_user(session) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        email=f"tree-{suffix}@test.io",
        username=f"tree-{suffix}",
        password_hash="x",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_display_newick_round_trips_and_falls_back_to_none(session):
    user = await _make_user(session)
    run = await RunRepository(session).create_run(
        method_id="gctree", params={}, user_id=user.id
    )

    repo = RunTreeRepository(session)
    await repo.replace_for_run(
        run.id,
        [
            {
                "tree_index": 0,
                "tree_id": "gctree-tree-1",
                "newick": "(seq1:1,seq2:1)naive:0;",
                "original_newick": "(seq1:1,seq2:1)naive:0;",
                "node_attributes": None,
                "lineage_plot": None,
                "label_to_sequence_id": {"seq1": "orig1"},
                "display_newick": "(orig1:1,'a:b':1)naive:0;",
            },
            {
                # A tree with no display_newick (e.g. legacy / other method).
                "tree_index": 1,
                "tree_id": "gctree-tree-2",
                "newick": "(seq3:1,seq4:1)naive:0;",
                "original_newick": "(seq3:1,seq4:1)naive:0;",
                "node_attributes": None,
                "lineage_plot": None,
                "label_to_sequence_id": None,
                # display_newick intentionally omitted
            },
        ],
    )
    await session.commit()

    with_display = await repo.get_tree_payload(run.id, "gctree-tree-1")
    assert with_display is not None
    assert with_display["display_newick"] == "(orig1:1,'a:b':1)naive:0;"

    without_display = await repo.get_tree_payload(run.id, "gctree-tree-2")
    assert without_display is not None
    assert without_display["display_newick"] is None
