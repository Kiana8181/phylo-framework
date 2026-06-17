"""One-shot backfill: re-slim every run's stored `result` JSON in place.

Past runs were written before tree_contract._lightweight_result learned how
to drop per-tree heavy fields and aggregate Dowser's discrete_trait_analysis
switches. Their `runs.result` rows can be 100+ MB. This script reads each row,
runs it through the current slim pipeline, and writes the slim version back.

The slim functions are idempotent — running this script twice yields the same
output. It is safe to re-run.

Usage:
    .venv/bin/python -m apps.api.scripts.backfill_slim_results [--dry-run] [--run-id <uuid>]

Reads DB connection params from environment via apps.api.config (same as the API).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.database.base import AsyncSessionLocal
from apps.api.database.models import Run
from apps.api.services.tree_contract import _lightweight_result, _slim_dowser_dta


def _slim_in_place(result: dict[str, Any]) -> dict[str, Any]:
    """Apply the current strip rules to an already-stored result dict.

    We can't call assemble_unified_tree_result here because the raw
    per-tree fields are already gone — but the heavy DTA block usually
    survives, so we focus on that.
    """
    slim = _lightweight_result(result)
    # _lightweight_result already invokes _slim_dowser_dta on the DTA block;
    # the explicit call below is just defensive in case a future version of
    # _lightweight_result changes that behavior.
    if isinstance(slim.get("discrete_trait_analysis"), dict):
        slim["discrete_trait_analysis"] = _slim_dowser_dta(slim["discrete_trait_analysis"])
    return slim


async def backfill_one(session: AsyncSession, run: Run, *, dry_run: bool) -> tuple[int, int]:
    original = run.result
    if not isinstance(original, dict):
        return 0, 0
    original_text = json.dumps(original)
    before_bytes = len(original_text)

    slim = _slim_in_place(original)
    slim_text = json.dumps(slim)
    after_bytes = len(slim_text)

    if after_bytes >= before_bytes:
        return before_bytes, after_bytes

    if not dry_run:
        await session.execute(update(Run).where(Run.id == run.id).values(result=slim))
        await session.commit()

    return before_bytes, after_bytes


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report sizes without writing.")
    parser.add_argument("--run-id", default=None, help="Only process this run id.")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        stmt = select(Run).where(Run.result.is_not(None))
        if args.run_id:
            stmt = stmt.where(Run.id == args.run_id)
        result = await session.execute(stmt)
        runs = list(result.scalars().all())
        print(f"Processing {len(runs)} run(s); dry_run={args.dry_run}")

        total_before = 0
        total_after = 0
        for run in runs:
            before, after = await backfill_one(session, run, dry_run=args.dry_run)
            if before == 0:
                print(f"  {run.id}: skipped (empty)")
                continue
            saved = before - after
            pct = (saved / before * 100.0) if before else 0.0
            print(
                f"  {run.id} ({run.method_id}): {before:>12,} -> {after:>10,} bytes "
                f"({pct:5.1f}% saved)"
            )
            total_before += before
            total_after += after

        print(
            f"\nTotal: {total_before:,} -> {total_after:,} bytes "
            f"({(total_before - total_after) / max(1, total_before) * 100.0:.1f}% saved)"
        )


if __name__ == "__main__":
    asyncio.run(main())
