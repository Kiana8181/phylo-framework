from __future__ import annotations

from typing import Any, TypedDict
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.models import RunTree


class RunTreeListItem(TypedDict):
    treeId: str
    treeIndex: int
    hasLineagePlot: bool
    hasServiceImage: bool
    cloneId: str | None


class RunTreePayload(TypedDict):
    treeId: str
    newick: str
    original_newick: str | None
    node_attributes: dict[str, Any] | None
    lineage_plot: dict[str, Any] | None
    label_to_sequence_id: dict[str, Any] | None
    service_image: dict[str, Any] | None


class RunTreeRepository:
    """Repository for run_trees table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def replace_for_run(self, run_id: UUID, trees: list[dict[str, Any]]) -> None:
        """Replace all tree rows for a run with the provided list.

        This method is intentionally idempotent for retry safety.
        It is still last-writer-wins if multiple workers write the same run concurrently.
        Callers must guarantee a run can transition to RUNNING only once before writing results.
        """
        await self.session.execute(delete(RunTree).where(RunTree.run_id == run_id))
        for item in trees:
            tree_id = str(item.get("tree_id") or "").strip()
            if not tree_id:
                raise ValueError("tree_id is required for run_trees rows")
            row = RunTree(
                run_id=run_id,
                tree_index=int(item.get("tree_index", 0)),
                tree_id=tree_id,
                newick=str(item.get("newick") or ""),
                original_newick=item.get("original_newick"),
                service_image=item.get("service_image"),
                node_attributes=item.get("node_attributes"),
                lineage_plot=item.get("lineage_plot"),
                label_to_sequence_id=item.get("label_to_sequence_id"),
            )
            self.session.add(row)

    async def list_for_run(self, run_id: UUID) -> list[RunTreeListItem]:
        stmt = (
            select(
                RunTree.tree_id,
                RunTree.tree_index,
                RunTree.lineage_plot.isnot(None),
                RunTree.service_image.isnot(None),
            )
            .where(RunTree.run_id == run_id)
            .order_by(RunTree.tree_index.asc())
        )
        result = await self.session.execute(stmt)
        out: list[RunTreeListItem] = []
        for tree_id, tree_index, has_lineage_plot, has_service_image in result.all():
            out.append(
                {
                    "treeId": str(tree_id),
                    "treeIndex": int(tree_index),
                    "hasLineagePlot": bool(has_lineage_plot),
                    "hasServiceImage": bool(has_service_image),
                    "cloneId": None,
                }
            )
        return out

    async def get_tree_payload(self, run_id: UUID, tree_id: str) -> RunTreePayload | None:
        stmt = (
            select(
                RunTree.tree_id,
                RunTree.newick,
                RunTree.original_newick,
                RunTree.node_attributes,
                RunTree.lineage_plot,
                RunTree.label_to_sequence_id,
                RunTree.service_image,
            )
            .where(RunTree.run_id == run_id, RunTree.tree_id == tree_id)
            .limit(1)
        )
        row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            return None

        (
            raw_tree_id,
            newick,
            original_newick,
            node_attributes,
            lineage_plot,
            label_to_sequence_id,
            service_image,
        ) = row
        return {
            "treeId": str(raw_tree_id),
            "newick": str(newick),
            "original_newick": str(original_newick) if original_newick is not None else None,
            "node_attributes": node_attributes if isinstance(node_attributes, dict) else None,
            "lineage_plot": lineage_plot if isinstance(lineage_plot, dict) else None,
            "label_to_sequence_id": (
                label_to_sequence_id if isinstance(label_to_sequence_id, dict) else None
            ),
            "service_image": service_image if isinstance(service_image, dict) else None,
        }
