"""Storage connectivity smoke test.

Verifies the configured object storage backend (default: self-hosted MinIO)
is reachable and that the dataset + artifact buckets support a full
upload -> exists -> download -> stream -> delete round-trip.

Run via the Node wrapper (``node scripts/storage-check.mjs``) or directly:

    python -m apps.api.scripts.storage_check
"""
from __future__ import annotations

import asyncio
import sys
import uuid

from apps.api.storage import (
    artifact_bucket,
    dataset_bucket,
    get_artifact_storage,
    get_dataset_storage,
)


async def _round_trip(label: str, storage, bucket: str | None) -> bool:
    key = f"_healthcheck/{uuid.uuid4().hex}.txt"
    payload = b"phylo storage healthcheck\n"
    where = f"{storage.get_storage_type()}:{bucket}" if bucket else storage.get_storage_type()
    print(f"[{label}] backend={where}")
    try:
        await storage.upload(payload, key, content_type="text/plain")
        if not await storage.exists(key):
            print(f"[{label}] FAIL: object missing after upload")
            return False

        downloaded = await storage.download(key)
        if downloaded != payload:
            print(f"[{label}] FAIL: download mismatch")
            return False

        streamed = b"".join([chunk async for chunk in storage.stream_download(key)])
        if streamed != payload:
            print(f"[{label}] FAIL: stream_download mismatch")
            return False

        await storage.delete(key)
        if await storage.exists(key):
            print(f"[{label}] FAIL: object still present after delete")
            return False

        print(f"[{label}] OK: upload/exists/download/stream/delete round-trip passed")
        return True
    except Exception as exc:  # noqa: BLE001 - surface any backend error clearly
        print(f"[{label}] FAIL: {type(exc).__name__}: {exc}")
        return False


async def main() -> int:
    ds = get_dataset_storage()
    art = get_artifact_storage()
    results = [
        await _round_trip("datasets", ds, dataset_bucket()),
        await _round_trip("artifacts", art, artifact_bucket()),
    ]
    ok = all(results)
    print("STORAGE CHECK:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
