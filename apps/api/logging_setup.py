"""Make the application's own log lines visible.

Neither uvicorn nor the worker configures the ``phylo`` logger namespace, so
without this its INFO lines (e.g. "email sent", the start-up line saying
whether email works) would be dropped and only warnings would appear, bare.
"""
from __future__ import annotations

import logging
import os
import sys

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging() -> None:
    """Idempotent: attach one stderr handler to the ``phylo`` namespace."""
    logger = logging.getLogger("phylo")
    if any(getattr(h, "_phylo_handler", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler._phylo_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    level = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    logger.setLevel(level if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else "INFO")
