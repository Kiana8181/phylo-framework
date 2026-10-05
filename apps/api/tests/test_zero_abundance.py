from uuid import UUID

import pytest

from apps.api.database.models import RunStatus
from apps.api.repositories.run_repository import RunRepository
from apps.api.repositories.run_tree_repository import RunTreeRepository
from apps.api.services.tree_contract import assemble_unified_tree_result


def test_zero_abundance_survives_normalization_and_layout():
    unified, rows = assemble_unified_tree_result(
        "gctree",
        {
            "ok": True,
            "trees": ["(A:1)GL;"],
            "node_abundances": {"GL": 0, "A": 4},
        },
    )

    assert unified["warnings"] == []
    assert rows[0]["node_attributes"]["GL"]["abundance"] == 0
    assert rows[0]["node_attributes"]["A"]["abundance"] == 4
    layout = {node["id"]: node for node in rows[0]["lineage_plot"]["nodes"]}
    assert layout["GL"]["abundance"] == 0
    assert layout["A"]["abundance"] == 4


def test_explicit_zero_wins_and_invalid_abundance_is_omitted():
    unified, rows = assemble_unified_tree_result(
        "dowser",
        {
            "ok": True,
            "trees": ["(A:1)GL;"],
            "node_attributes": {"A": {"abundance": 9}},
            "annotations": [[{"label": "A", "duplicate_count": 12}]],
            "node_abundances": {"A": 0, "GL": float("inf")},
        },
    )

    attrs = rows[0]["node_attributes"]
    assert attrs["A"]["abundance"] == 0
    assert "abundance" not in attrs["GL"]
    assert any(w.get("code") == "INVALID_NODE_ABUNDANCE" for w in unified["warnings"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zero_abundance_round_trips_through_database_and_tree_api(
    client, account, session
):
    _, rows = assemble_unified_tree_result(
        "gctree",
        {
            "ok": True,
            "trees": ["(A:1)GL;"],
            "node_abundances": {"GL": 0, "A": 4},
        },
    )
    run = await RunRepository(session).create_run(
        method_id="gctree", params={}, user_id=UUID(account["user"]["id"])
    )
    run.status = RunStatus.DONE
    tree_id = rows[0]["tree_id"]
    await RunTreeRepository(session).replace_for_run(run.id, rows)
    await session.commit()

    response = await client.get(f"/runs/{run.id}/trees/{tree_id}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["newick"] == "(A:1)GL;"
    assert payload["node_attributes"]["GL"]["abundance"] == 0
    assert payload["node_attributes"]["A"]["abundance"] == 4
    layout = {node["id"]: node for node in payload["lineage_plot"]["nodes"]}
    assert layout["GL"]["abundance"] == 0
