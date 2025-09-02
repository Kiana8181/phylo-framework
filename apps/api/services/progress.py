import asyncio
from typing import Dict, Any

async def soft_progress(store: Dict[str, Dict[str, Any]], run_id: str,
                        floor: int = 10, ceiling: int = 95, step: int = 5, interval: float = 2.0):
    try:
        while True:
            info = store.get(run_id)
            if not info or info.get("status") != "RUNNING":
                return
            cur = int(info.get("progress") or floor)
            if cur < ceiling:
                store[run_id] = {**info, "progress": min(cur + step, ceiling), "message": info.get("message") or "Processing..."}
            await asyncio.sleep(interval)
    except Exception:
        return
